"""Restricted reserve operations in owned PITR paths and units."""

import base64
import hashlib
import io
import json
import os
import pwd
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

from pitr_store import atomic_json, digest, safe_remove_tree

ROOT = Path("/opt/ugc-pitr")
ETC = Path("/etc/ugc-pitr")
STATE = Path("/var/lib/ugc-pitr")
RESTORE = Path("/var/lib/ugc-pitr-restore")
AGE_URL = (
    "https://github.com/FiloSottile/age/releases/download/v1.3.2/"
    "age-v1.3.2-linux-amd64.tar.gz"
)
AGE_SHA = "cbe24006683f8eb669266162894b9a522a1af52f2665fbc63a4bb032ed26ac10"
PG_IMAGE = (
    "postgis/postgis@sha256:"
    "44126d872ac91993766c341e369c539e8196614321765d36a6f1bab0419a5fa5"
)
UNITS = (
    "ugc-pitr.slice",
    "ugc-pitr-receiver.service",
    "ugc-pitr-base.service",
    "ugc-pitr-base.timer",
    "ugc-pitr-restore.service",
)
SCRIPTS = (
    "pitr_operator.py",
    "pitr_tunnel.py",
    "pitr_store.py",
    "pitr_receiver.py",
    "pitr_restore_isolated.py",
    "pitr_fetch_wal.sh",
)
# Fixed names observed in the reserve audit; never issue a mutating command to
# these units. Capture their PIDs and configuration at install for comparison.
NEIGHBORS = (
    "reels-editing-worker",
    "reels-editing-api",
    "reels-editing-bot",
    "reels-editing-payment-reconcile",
    "reels-editing-refund",
    "kvartirnik-bot",
    "kvartirnik-db",
    "kvartirnik-teleprompter",
    "umc-bot-traffic",
    "umc-bot-traffic-links",
    "postgresql@16-main",
    "nginx",
    "umc-external-monitor",
    "zabbix-agent",
)


def run(command, *, input=None, timeout=60):
    result = subprocess.run(
        command, input=input, capture_output=True, timeout=timeout
    )
    if result.returncode:
        raise RuntimeError("Reserve operation failed: " + Path(command[0]).name)
    return result.stdout.decode().strip()


def systemctl(action, unit):
    if unit not in UNITS or action not in (
        "start",
        "stop",
        "enable",
        "disable",
    ):
        raise ValueError("Only owned PITR units may be changed")
    return run(["/usr/bin/systemctl", action, unit], timeout=1250)


def neighbors():
    result = {}
    for unit in NEIGHBORS:
        text = run(
            [
                "/usr/bin/systemctl",
                "show",
                unit + ".service",
                "--property=MainPID,ActiveState,MemoryMax,CPUQuotaPerSecUSec,"
                "FragmentPath,ExecMainStartTimestampMonotonic",
            ]
        )
        result[unit] = dict(line.split("=", 1) for line in text.splitlines())
    return result


def unchanged(before):
    current = neighbors()
    if current != before:
        raise RuntimeError(
            "Reserve neighbor state changed; review before continuing"
        )


def private_file(path, content):
    path = Path(path)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def download(url, maximum):
    with urllib.request.urlopen(url, timeout=60) as response:
        data = response.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError("Public artifact exceeds its size limit")
    return data


def install(payload):  # noqa: C901
    revision = payload["revision"]
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("A full reviewed main commit is required")
    if ETC.exists() or STATE.exists() or RESTORE.exists():
        raise ValueError("Existing reserve paths require manual review")
    if any(Path("/etc/systemd/system", u).exists() for u in UNITS):
        raise ValueError("Existing PITR units must not be overwritten")
    baseline = neighbors()
    try:
        pwd.getpwnam("ugc-pitr")
    except KeyError:
        pass
    else:
        raise ValueError("Existing service user must not be adopted")
    run(
        [
            "/usr/sbin/useradd",
            "--system",
            "--home-dir",
            str(STATE),
            "--shell",
            "/usr/sbin/nologin",
            "ugc-pitr",
        ]
    )
    account = pwd.getpwnam("ugc-pitr")
    for path in (ETC, STATE, RESTORE):
        path.mkdir(mode=0o700)
    ETC.chmod(0o750)
    os.chown(ETC, 0, account.pw_gid)
    os.chown(STATE, account.pw_uid, account.pw_gid)
    release = ROOT / "releases" / revision
    release.mkdir(mode=0o755, parents=True, exist_ok=True)
    ROOT.chmod(0o755)
    (ROOT / "releases").chmod(0o755)
    release.chmod(0o755)
    for name in SCRIPTS:
        target = release / name
        if name == "pitr_operator.py" and target.exists():
            continue
        data = download(
            f"https://raw.githubusercontent.com/darbulat/ugc/"
            f"{revision}/scripts/{name}",
            256 * 1024,
        )
        private_file(target, data)
        target.chmod(0o755 if name.endswith(".sh") else 0o644)
    for name in UNITS:
        data = download(
            f"https://raw.githubusercontent.com/darbulat/ugc/"
            f"{revision}/config/pitr/{name}",
            16 * 1024,
        )
        private_file(release / name, data)
        shutil.copyfile(release / name, Path("/etc/systemd/system", name))
        Path("/etc/systemd/system", name).chmod(0o644)
    (ROOT / "current").symlink_to(release)
    binaries = ROOT / "bin"
    binaries.mkdir(mode=0o755)
    archive = download(AGE_URL, 16 * 1024**2)
    if hashlib.sha256(archive).hexdigest() != AGE_SHA:
        raise ValueError("Pinned age archive checksum mismatch")
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as tar:
        for name in ("age", "age-keygen"):
            data = tar.extractfile("age/" + name).read(16 * 1024**2)
            private_file(binaries / name, data)
            (binaries / name).chmod(0o755)
    run([str(binaries / "age-keygen"), "-o", str(ETC / "pitr.identity")])
    run(
        [
            "/usr/bin/ssh-keygen",
            "-q",
            "-t",
            "ed25519",
            "-N",
            "",
            "-C",
            "ugc-pitr-reserve-v1",
            "-f",
            str(ETC / "tunnel_key"),
        ]
    )
    private_file(ETC / "known_hosts", payload["known_hosts"].encode())
    (ETC / "known_hosts").chmod(0o644)
    atomic_json(
        ETC / "installed.json",
        {
            "revision": revision,
            "uid": account.pw_uid,
            "gid": account.pw_gid,
            "baseline": baseline,
            "image": PG_IMAGE,
        },
    )
    run(["/usr/bin/systemctl", "daemon-reload"])
    unchanged(baseline)
    return public()


def public():
    return {
        "recipient": run(
            [str(ROOT / "bin/age-keygen"), "-y", str(ETC / "pitr.identity")]
        ),
        "tunnel_public_key": (ETC / "tunnel_key.pub").read_text().strip(),
        "revision": json.loads((ETC / "installed.json").read_text())[
            "revision"
        ],
    }


def bootstrap(payload):
    if (ETC / "pgpass").exists() or (ETC / "config.json").exists():
        raise ValueError("Existing credentials must not be replaced")
    cipher = base64.b64decode(payload["bootstrap_base64"], validate=True)
    if len(cipher) > 64 * 1024:
        raise ValueError("Oversized encrypted bootstrap")
    result = run(
        [
            str(ROOT / "bin/age"),
            "--decrypt",
            "--identity",
            str(ETC / "pitr.identity"),
        ],
        input=cipher,
    )
    secret = json.loads(result)
    if not re.fullmatch(
        r"127\.0\.0\.1:16543:\*:ugc_pitr_v1:[A-Za-z0-9_-]+\n", secret["pgpass"]
    ):
        raise ValueError("Invalid private replication credential")
    owner = payload["owner_recipient"]
    config = secret | {
        "version": 1,
        "root": str(STATE / "archive"),
        "slot": "ugc_pitr_v1",
        "ssh_host": "31.59.106.143",
        "pg_host": "127.0.0.1",
        "pg_port": 16543,
        "pg_user": "ugc_pitr_v1",
        "pg_bin": "/usr/lib/postgresql/16/bin",
        "age": str(ROOT / "bin/age"),
        "recipients": [public()["recipient"], owner],
        "max_bytes": 8 * 1024**3,
        "min_free_bytes": 16 * 1024**3,
        "keep_days": 7,
        "switch_seconds": 300,
    }
    config.pop("pgpass")
    from pitr_receiver import load_config, store_from

    private_file(ETC / "pgpass", secret["pgpass"].encode())
    atomic_json(ETC / "config.json", config)
    (ETC / "config.json").chmod(0o644)
    load_config(ETC / "config.json")
    archive = store_from(config)
    account = pwd.getpwnam("ugc-pitr")
    for path in [archive.root, *archive.root.rglob("*")]:
        os.chown(path, account.pw_uid, account.pw_gid)
    return {"configured": True, "system_id": secret["system_id"]}


def status():
    values = {}
    for unit in UNITS:
        values[unit] = run(
            [
                "/usr/bin/systemctl",
                "show",
                unit,
                "--property=ActiveState,SubState,MemoryCurrent,"
                "MemoryPeak,MemoryMax,CPUQuotaPerSecUSec,MainPID,"
                "Result,OOMPolicy",
            ]
        )
    path = STATE / "archive/status.json"
    return {
        "units": values,
        "archive": json.loads(path.read_text()) if path.exists() else None,
        "neighbors": neighbors(),
        "free_bytes": shutil.disk_usage(STATE).free,
    }


def prepare_restore(payload):
    from pitr_receiver import load_config, memory_headroom
    from pitr_restore_isolated import prepare

    memory_headroom(3 * 1024**3)
    before = neighbors()
    if not (ROOT / "runtime/usr/lib/postgresql/16/bin/postgres").is_file():
        raise ValueError("Compatible isolated runtime has not been installed")
    # Repeated attempts preserve previous evidence instead of replacing it.
    if (RESTORE / "current").exists():
        raise ValueError("An earlier isolated restore must be reviewed first")
    config = load_config(ETC / "config.json")
    directory = prepare(config, payload["probe"], ETC / "pitr.identity")
    account = pwd.getpwnam("ugc-pitr")
    for path in [directory, *directory.rglob("*")]:
        if path.is_symlink():
            raise ValueError("Unsafe isolated restore path")
        os.chown(path, account.pw_uid, account.pw_gid)
    (RESTORE / "current").symlink_to(directory)
    unchanged(before)
    return {"prepared": directory.name}


def clean_restore():
    active = run(
        [
            "/usr/bin/systemctl",
            "show",
            "ugc-pitr-restore.service",
            "--property=ActiveState",
            "--value",
        ]
    )
    if active not in ("inactive", "failed"):
        raise ValueError("Stop the owned isolated recovery before cleanup")
    current = RESTORE / "current"
    directory = current.resolve(strict=True)
    proof = json.loads((directory / "verified.json").read_text())
    if not proof.get("in_recovery") or proof.get("paused") != "paused":
        raise ValueError("Preserve an unverified recovery for investigation")
    atomic_json(ETC / "last-restore-proof.json", proof)
    current.unlink()
    safe_remove_tree(directory, RESTORE)
    return {"verified_plaintext_removed": True}


def verify_restore():
    from pitr_receiver import load_config
    from pitr_restore_isolated import verify

    before = neighbors()
    result = verify(load_config(ETC / "config.json"), RESTORE / "current")
    unchanged(before)
    return result


def runtime(payload):  # noqa: C901
    """Read one trusted public image export from stdin into an owned rootfs."""
    if payload["image"] != PG_IMAGE:
        raise ValueError("Only the audited public PostgreSQL image is allowed")
    target = ROOT / "runtime"
    if target.exists():
        raise ValueError("Existing private runtime must not be overwritten")
    maximum = 2 * 1024**3
    if shutil.disk_usage(ROOT).free < 20 * 1024**3:
        raise ValueError("Insufficient reserve disk headroom")
    target.mkdir(mode=0o755)
    total = 0
    # The export contains no database volume. Never extract into host paths.
    with tarfile.open(fileobj=sys.stdin.buffer, mode="r|") as tar:
        for member in tar:
            parts = Path(member.name).parts
            if member.name.startswith("/") or ".." in parts:
                raise ValueError("Unsafe runtime path")
            if member.isdev() or member.isfifo():
                continue
            if not (
                member.isfile()
                or member.isdir()
                or member.issym()
                or member.islnk()
            ):
                raise ValueError("Unsupported runtime entry")
            if parts and parts[0] in ("proc", "sys", "dev"):
                continue
            if member.issym() and member.linkname.startswith("/"):
                # Absolute image symlinks must remain relative to this rootfs
                # even during extraction, before systemd chroots the process.
                member.linkname = os.path.relpath(
                    target / member.linkname.lstrip("/"),
                    (target / member.name).parent,
                )
            member.mode &= 0o777
            total += member.size
            if total > maximum:
                raise ValueError("Private runtime exceeds reviewed budget")
            tar.extract(member, target, filter="data")
    for path in ("restore", "archive", "tools"):
        (target / path).mkdir(mode=0o755, exist_ok=True)
    account = pwd.getpwnam("ugc-pitr")
    with (target / "etc/passwd").open("a") as out:
        out.write(
            f"ugc-pitr:x:{account.pw_uid}:{account.pw_gid}:PITR:/restore:/bin/false\n"
        )
    with (target / "etc/group").open("a") as out:
        out.write(f"ugc-pitr:x:{account.pw_gid}:\n")
    atomic_json(
        ETC / "runtime.json",
        {
            "image": PG_IMAGE,
            "bytes": total,
            "postgres_sha256": digest(
                target / "usr/lib/postgresql/16/bin/postgres"
            ),
        },
    )
    return {"runtime_installed": True, "bytes": total}


def main():  # noqa: C901, PLR0912
    os.umask(0o077)
    if os.geteuid() != 0:
        raise ValueError(
            "Reserve operator requires its restricted root command"
        )
    action = os.environ.get("SSH_ORIGINAL_COMMAND", "")
    if len(sys.argv) == 2 and sys.argv[1] == "install":
        result = install(json.load(sys.stdin))
    elif action == "ugc-pitr-public":
        result = public()
    elif action == "ugc-pitr-status":
        result = status()
    elif action == "ugc-pitr-bootstrap":
        result = bootstrap(json.load(sys.stdin))
    elif action == "ugc-pitr-runtime":
        result = runtime({"image": PG_IMAGE})
    elif action == "ugc-pitr-prepare-restore":
        result = prepare_restore(json.load(sys.stdin))
    elif action == "ugc-pitr-clean-restore":
        result = clean_restore()
    elif action == "ugc-pitr-verify-restore":
        result = verify_restore()
    elif action in (
        "ugc-pitr-start",
        "ugc-pitr-base",
        "ugc-pitr-start-restore",
        "ugc-pitr-stop-restore",
        "ugc-pitr-enable",
    ):
        before = neighbors()
        if action == "ugc-pitr-start":
            systemctl("start", "ugc-pitr-receiver.service")
        elif action == "ugc-pitr-base":
            systemctl("start", "ugc-pitr-base.service")
        elif action == "ugc-pitr-start-restore":
            from pitr_receiver import memory_headroom

            memory_headroom(3 * 1024**3)
            systemctl("start", "ugc-pitr-restore.service")
        elif action == "ugc-pitr-stop-restore":
            systemctl("stop", "ugc-pitr-restore.service")
        else:
            if not (ETC / "last-restore-proof.json").is_file():
                raise ValueError("Verify a real isolated recovery first")
            systemctl("enable", "ugc-pitr-receiver.service")
            systemctl("enable", "ugc-pitr-base.timer")
            systemctl("start", "ugc-pitr-base.timer")
        unchanged(before)
        result = {"completed": action}
    else:
        raise ValueError("Command is outside the restricted PITR allowlist")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
