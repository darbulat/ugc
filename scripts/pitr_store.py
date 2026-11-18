"""Bounded, encrypted PostgreSQL archives isolated from application data."""

import gzip
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

SEGMENT_BYTES = 16 * 1024**2
CHUNK = 64 * 1024
WAL_NAME = re.compile(r"[0-9A-F]{24}\Z")
BASE_NAME = re.compile(r"base-[0-9]{8}T[0-9]{12}Z-[0-9a-f]{8}\Z")
SYSTEM_ID = re.compile(r"[0-9]{10,20}\Z")


def digest(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(CHUNK), b""):
            result.update(chunk)
    return result.hexdigest()


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_json(path, value):
    path = Path(path)
    fd, name = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as out:
            json.dump(value, out, sort_keys=True)
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
        os.replace(name, path)
        sync_directory(path.parent)
    finally:
        Path(name).unlink(missing_ok=True)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("An explicit recovery timezone is required")
    return parsed.timestamp()


def lsn_number(value):
    if not re.fullmatch(r"[0-9A-F]{1,8}/[0-9A-F]{1,8}", value):
        raise ValueError("Invalid PostgreSQL LSN")
    high, low = value.split("/")
    return (int(high, 16) << 32) + int(low, 16)


def wal_number(name):
    if not WAL_NAME.fullmatch(name) or int(name[16:], 16) >= 256:
        raise ValueError("Invalid 16 MiB WAL filename")
    return int(name[8:16], 16) * 256 + int(name[16:], 16)


def wal_filename(timeline, number):
    return f"{timeline:08X}{number // 256:08X}{number % 256:08X}"


def safe_remove_tree(path, parent):
    path, parent = Path(path), Path(parent).resolve(strict=True)
    if path.is_symlink() or path.parent.resolve() != parent:
        raise ValueError("Refusing to remove a foreign directory")
    if not path.name.startswith(("base-work-", "restore-work-")):
        raise ValueError("Refusing to remove an unowned directory")
    shutil.rmtree(path)
    sync_directory(parent)


class Store:
    def __init__(
        self,
        root,
        system_id,
        age,
        recipients,
        *,
        max_bytes=8 * 1024**3,
        min_free_bytes=16 * 1024**3,
    ):
        self.root = Path(root)
        self.system_id = str(system_id)
        if not SYSTEM_ID.fullmatch(self.system_id):
            raise ValueError("Invalid cluster identity")
        self.age = str(age)
        self.recipients = tuple(recipients)
        self._verified = {}
        if not self.recipients or any(
            not re.fullmatch(r"age1[0-9a-z]{58}", r) for r in self.recipients
        ):
            raise ValueError("Invalid encryption recipients")
        self.max_bytes, self.min_free_bytes = max_bytes, min_free_bytes
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.root.is_symlink() or self.root.stat().st_mode & 0o077:
            raise ValueError("Archive root must be private and not a symlink")
        marker = self.root / "cluster.json"
        if marker.exists():
            if json.loads(marker.read_text()) != {"system_id": self.system_id}:
                raise ValueError("Archive belongs to another cluster")
        else:
            if any(self.root.iterdir()):
                raise ValueError("Refusing to adopt an existing directory")
            atomic_json(marker, {"system_id": self.system_id})
        for name in ("wal", "base", "spool", "work"):
            path = self.root / name
            path.mkdir(mode=0o700, exist_ok=True)
            if path.is_symlink() or path.stat().st_mode & 0o077:
                raise ValueError("Archive subdirectory is not private")

    def capacity(self, additional=0):
        used = sum(
            p.stat().st_size
            for p in self.root.rglob("*")
            if p.is_file() and not p.is_symlink()
        )
        free = shutil.disk_usage(self.root).free
        if used + additional > self.max_bytes:
            raise RuntimeError("PITR archive capacity exceeded")
        if free - additional < self.min_free_bytes:
            raise RuntimeError("Insufficient disk headroom for PITR")
        return used

    def metadata(self, kind):
        return [
            json.loads(p.read_text())
            for p in sorted((self.root / kind).glob("*.json"))
        ]

    def _encrypt(self, folder, stem, writer, metadata):
        target = self.root / folder / (stem + ".age")
        sidecar = target.with_suffix(".json")
        if target.exists() or sidecar.exists():
            raise FileExistsError("PITR artifact already exists")
        self.capacity()
        fd, pending = tempfile.mkstemp(prefix=".pending-", dir=target.parent)
        process = None
        try:
            with os.fdopen(fd, "wb") as out, tempfile.TemporaryFile() as err:
                command = [self.age, "--encrypt"]
                for recipient in self.recipients:
                    command += ["--recipient", recipient]
                process = subprocess.Popen(
                    command, stdin=subprocess.PIPE, stdout=out, stderr=err
                )
                try:
                    writer(process.stdin)
                    process.stdin.close()
                    if process.wait(timeout=120):
                        raise RuntimeError("PITR encryption failed")
                except BaseException:
                    process.kill()
                    process.wait()
                    raise
                out.flush()
                os.fsync(out.fileno())
            self.capacity()
            os.rename(pending, target)
            sync_directory(target.parent)
            metadata = metadata | {
                "system_id": self.system_id,
                "artifact": target.name,
                "cipher_sha256": digest(target),
                "cipher_bytes": target.stat().st_size,
            }
            atomic_json(sidecar, metadata)
            return metadata
        finally:
            Path(pending).unlink(missing_ok=True)
            if process and process.stdin:
                process.stdin.close()

    def archive_wal(self, path):
        path = Path(path)
        number = wal_number(path.name)
        if path.is_symlink() or path.stat().st_size != SEGMENT_BYTES:
            raise ValueError("WAL segment is incomplete or unsafe")
        sha = digest(path)
        meta_path = self.root / "wal" / (path.name + ".json")
        if meta_path.exists():
            metadata = json.loads(meta_path.read_text())
            self.check_artifact(metadata, "wal")
            if metadata["plain_sha256"] != sha:
                raise ValueError("Conflicting WAL segment content")
            return metadata
        # A crash between ciphertext rename and metadata publication is safe
        # to retry only while the complete original WAL still exists.
        orphan = self.root / "wal" / (path.name + ".age")
        if orphan.exists():
            if orphan.is_symlink():
                raise ValueError("Unsafe incomplete WAL artifact")
            orphan.unlink()
            sync_directory(orphan.parent)

        def write(out):
            with (
                gzip.GzipFile(fileobj=out, mode="wb", mtime=0) as encoded,
                path.open("rb") as source,
            ):
                shutil.copyfileobj(source, encoded, CHUNK)

        return self._encrypt(
            "wal",
            path.name,
            write,
            {
                "kind": "wal",
                "name": path.name,
                "number": number,
                "timeline": int(path.name[:8], 16),
                "plain_sha256": sha,
                "archived_at": utc_now(),
            },
        )

    def archive_base(
        self, path, *, started_at, finished_at, recovery_parameters
    ):
        path = Path(path)
        if timestamp(finished_at) < timestamp(started_at):
            raise ValueError("Invalid base backup time range")
        manifest = json.loads((path / "backup_manifest").read_text())
        ranges = manifest["WAL-Ranges"]
        if len(ranges) != 1:
            raise ValueError("A single PostgreSQL timeline is required")
        wal_range = ranges[0]
        first = lsn_number(wal_range["Start-LSN"])
        last = lsn_number(wal_range["End-LSN"])
        if last < first:
            raise ValueError("Invalid backup WAL range")
        for item in path.rglob("*"):
            if item.is_symlink():
                raise ValueError("External tablespaces/WAL paths unsupported")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        stem = "base-" + stamp + "-" + os.urandom(4).hex()

        def write(out):
            with tarfile.open(fileobj=out, mode="w|gz") as tar:
                for item in sorted(path.iterdir()):
                    tar.add(item, arcname=item.name)

        return self._encrypt(
            "base",
            stem,
            write,
            {
                "kind": "base",
                "started_at": started_at,
                "finished_at": finished_at,
                "timeline": wal_range["Timeline"],
                "start_lsn": wal_range["Start-LSN"],
                "end_lsn": wal_range["End-LSN"],
                "recovery_parameters": recovery_parameters,
                "manifest_sha256": digest(path / "backup_manifest"),
                "plain_bytes": sum(
                    p.stat().st_size for p in path.rglob("*") if p.is_file()
                ),
            },
        )

    def check_artifact(self, metadata, kind):
        name = metadata.get("artifact", "")
        stem = name.removesuffix(".age")
        valid = (
            WAL_NAME.fullmatch(stem)
            if kind == "wal"
            else (BASE_NAME.fullmatch(stem))
        )
        if (
            not name.endswith(".age")
            or not valid
            or metadata.get("system_id") != self.system_id
        ):
            raise ValueError("Invalid PITR artifact identity")
        if kind == "wal" and (
            metadata["number"] != wal_number(stem)
            or metadata["timeline"] != int(stem[:8], 16)
        ):
            raise ValueError("WAL metadata does not match its filename")
        path = self.root / kind / name
        stat = path.stat()
        fingerprint = (
            stat.st_ino,
            stat.st_size,
            stat.st_mtime_ns,
            metadata["cipher_sha256"],
        )
        if path.is_symlink():
            raise ValueError("PITR artifact checksum mismatch")
        if self._verified.get(path) != fingerprint:
            if digest(path) != metadata["cipher_sha256"]:
                raise ValueError("PITR artifact checksum mismatch")
            self._verified[path] = fingerprint
        return path

    def select_base(self, target_time):
        target = timestamp(target_time)
        usable = [
            m
            for m in self.metadata("base")
            if timestamp(m["finished_at"]) < target
        ]
        if not usable:
            raise ValueError("No verified base predates the recovery target")
        selected = max(usable, key=lambda m: timestamp(m["finished_at"]))
        self.check_artifact(selected, "base")
        return selected

    def wal_chain(self, base, through_lsn):
        first = lsn_number(base["end_lsn"]) // SEGMENT_BYTES
        last = max(first, (lsn_number(through_lsn) - 1) // SEGMENT_BYTES)
        available = {
            m["number"]: m
            for m in self.metadata("wal")
            if m["timeline"] == base["timeline"]
        }
        result = []
        for number in range(first, last + 1):
            if number not in available:
                raise ValueError("Gap in the WAL recovery chain")
            current = available[number]
            self.check_artifact(current, "wal")
            result.append(current)
        return result

    def prune(self, keep_days=7, now=None):
        cutoff = (time.time() if now is None else now) - keep_days * 86400
        bases = sorted(
            self.metadata("base"), key=lambda m: timestamp(m["finished_at"])
        )
        if not bases:
            return
        # Keep a base before the boundary and at least two verified bases.
        older = [b for b in bases if timestamp(b["finished_at"]) < cutoff]
        retained = [b for b in bases if timestamp(b["finished_at"]) >= cutoff]
        for base in bases[-2:] + older[-1:]:
            if base not in retained:
                retained.append(base)
        for base in retained:
            self.check_artifact(base, "base")
        minimum = min(
            lsn_number(b["end_lsn"]) // SEGMENT_BYTES for b in retained
        )
        timelines = {b["timeline"] for b in retained}
        removals = [("base", b) for b in bases if b not in retained]
        removals += [
            ("wal", w)
            for w in self.metadata("wal")
            if w["timeline"] in timelines and w["number"] < minimum
        ]
        for kind, metadata in removals:
            path = self.check_artifact(metadata, kind)
            path.unlink()
            path.with_suffix(".json").unlink()
            sync_directory(path.parent)

    def restore_wal(self, name, destination, identity):
        wal_number(name)
        metadata = json.loads(
            (self.root / "wal" / (name + ".json")).read_text()
        )
        source = self.check_artifact(metadata, "wal")
        destination = Path(destination)
        fd, pending = tempfile.mkstemp(prefix=".wal-", dir=destination.parent)
        process = None
        try:
            with os.fdopen(fd, "wb") as out, tempfile.TemporaryFile() as err:
                process = subprocess.Popen(
                    [
                        self.age,
                        "--decrypt",
                        "--identity",
                        str(identity),
                        str(source),
                    ],
                    stdout=subprocess.PIPE,
                    stderr=err,
                )
                sha, size = hashlib.sha256(), 0
                with gzip.GzipFile(fileobj=process.stdout) as decoded:
                    for chunk in iter(lambda: decoded.read(CHUNK), b""):
                        size += len(chunk)
                        if size > SEGMENT_BYTES:
                            raise ValueError("Oversized decrypted WAL")
                        out.write(chunk)
                        sha.update(chunk)
                if process.wait(timeout=30) or size != SEGMENT_BYTES:
                    raise ValueError("WAL decryption/size verification failed")
                if sha.hexdigest() != metadata["plain_sha256"]:
                    raise ValueError("Decrypted WAL checksum mismatch")
                out.flush()
                os.fsync(out.fileno())
            os.replace(pending, destination)
            sync_directory(destination.parent)
        finally:
            if process and process.poll() is None:
                process.kill()
                process.wait()
            if process and process.stdout:
                process.stdout.close()
            Path(pending).unlink(missing_ok=True)

    def restore_base(self, metadata, destination, identity):
        source = self.check_artifact(metadata, "base")
        destination = Path(destination)
        if destination.exists():
            raise ValueError("Recovery requires a new empty destination")
        self.capacity(metadata["plain_bytes"])
        destination.mkdir(mode=0o700)
        process = None
        try:
            with tempfile.TemporaryFile() as err:
                process = subprocess.Popen(
                    [
                        self.age,
                        "--decrypt",
                        "--identity",
                        str(identity),
                        str(source),
                    ],
                    stdout=subprocess.PIPE,
                    stderr=err,
                )
                total = 0
                with tarfile.open(fileobj=process.stdout, mode="r|gz") as tar:
                    for member in tar:
                        if not (member.isfile() or member.isdir()):
                            raise ValueError("Unsafe base archive entry")
                        total += member.size
                        if total > metadata["plain_bytes"]:
                            raise ValueError("Oversized decrypted base backup")
                        tar.extract(member, destination, filter="data")
                # Consume the authenticated age trailer, including gzip/tar
                # padding, before checking the decryptor exit status.
                while process.stdout.read(CHUNK):
                    pass
                if process.wait(timeout=30):
                    raise ValueError("Base backup decryption failed")
            if (
                digest(destination / "backup_manifest")
                != (metadata["manifest_sha256"])
            ):
                raise ValueError("Restored backup manifest checksum mismatch")
        finally:
            if process and process.poll() is None:
                process.kill()
                process.wait()
            if process and process.stdout:
                process.stdout.close()
