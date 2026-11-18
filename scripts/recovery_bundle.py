"""Stream a recovery archive directly into age public-key encryption."""

import hashlib
import io
import json
import posixpath
import subprocess
import sys
import tarfile
from pathlib import Path


class HashedReader:
    def __init__(self, source):
        self.source = source
        self.digest = hashlib.sha256()

    def read(self, size=-1):
        content = self.source.read(size)
        self.digest.update(content)
        return content


def add_memory(archive, name, content, manifest):
    validate_name(name)
    if name in manifest:
        raise ValueError("Duplicate recovery archive path")
    payload = content.encode()
    item = tarfile.TarInfo(name)
    item.size = len(payload)
    item.mode = 0o600
    archive.addfile(item, io.BytesIO(payload))
    manifest[name] = {
        "size": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def add_path(archive, path, name, manifest):
    validate_name(name)
    if name in manifest:
        raise ValueError("Duplicate recovery archive path")
    item = archive.gettarinfo(str(path), arcname=name)
    if item.issym():
        target = posixpath.normpath(
            posixpath.join(posixpath.dirname(name), item.linkname)
        )
        if target.split("/")[0] != name.split("/")[0]:
            raise ValueError("Recovery symlink points outside the archive")
        archive.addfile(item)
        manifest[name] = {"symlink": item.linkname}
    elif item.isfile():
        with path.open("rb") as source:
            reader = HashedReader(source)
            archive.addfile(item, reader)
        manifest[name] = {
            "size": item.size,
            "sha256": reader.digest.hexdigest(),
        }
    elif item.islnk():
        if item.linkname not in manifest:
            raise ValueError("Recovery hardlink target is missing")
        archive.addfile(item)
        manifest[name] = {"hardlink": item.linkname}
    elif item.isdir():
        archive.addfile(item)
    else:
        raise ValueError("Unsupported recovery file type")


def validate_name(name):
    if not name or name.startswith("/") or ".." in name.split("/"):
        raise ValueError("Invalid recovery archive path")


def create_bundle(age, recipient, sources, memory, destination):
    process = subprocess.Popen(
        [str(age), "--encrypt", "--recipient", recipient],
        stdin=subprocess.PIPE,
        stdout=destination,
        stderr=subprocess.PIPE,
    )
    manifest = {}
    try:
        with tarfile.open(
            fileobj=process.stdin, mode="w|gz", dereference=False
        ) as archive:
            for name, content in memory.items():
                add_memory(archive, name, content, manifest)
            for source in sources:
                root = Path(source["path"])
                if not root.exists():
                    raise FileNotFoundError(
                        "Required recovery source is missing"
                    )
                paths = [root]
                if root.is_dir():
                    paths += sorted(root.rglob("*"))
                for path in paths:
                    name = source["name"]
                    if path != root:
                        name += "/" + path.relative_to(root).as_posix()
                    add_path(archive, path, name, manifest)
            add_memory(
                archive,
                "manifest.json",
                json.dumps(manifest, sort_keys=True),
                {},
            )
        process.stdin.close()
        if process.wait(timeout=30):
            raise RuntimeError("Recovery encryption failed")
        process.stderr.read()
    except BaseException:
        process.kill()
        process.wait()
        raise
    finally:
        process.stdin.close()
        process.stderr.close()
    return manifest


def main():
    plan = json.load(sys.stdin)
    create_bundle(
        Path(plan["age_binary"]),
        plan["recipient"],
        plan["sources"],
        plan["memory"],
        sys.stdout.buffer,
    )


if __name__ == "__main__":
    main()
