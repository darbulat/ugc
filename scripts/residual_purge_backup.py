"""Authenticated, owner-only selective backups; never plaintext on disk."""

import json
import os
import stat
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from scripts.residual_purge_catalog import require


def private_read(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode), "not_a_regular_private_file")
        require(info.st_uid == os.getuid(), "private_file_wrong_owner")
        require(info.st_mode & 0o077 == 0, "private_file_permissions")
        return stream.read()


def write_encrypted(path, key_path, payload):
    path = Path(path)
    info = path.parent.stat()
    require(
        info.st_uid == os.getuid() and info.st_mode & 0o077 == 0,
        "backup_directory_must_be_private",
    )
    token = Fernet(private_read(key_path).strip()).encrypt(
        json.dumps(payload, sort_keys=True).encode()
    )
    fd = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
    )
    with os.fdopen(fd, "wb") as stream:
        stream.write(token)
        stream.flush()
        os.fsync(stream.fileno())
    require(
        read_encrypted(path, key_path) == payload, "backup_roundtrip_failed"
    )


def read_encrypted(path, key_path):
    try:
        return json.loads(
            Fernet(private_read(key_path).strip()).decrypt(private_read(path))
        )
    except (InvalidToken, ValueError):
        raise ValueError("invalid_encrypted_backup") from None
