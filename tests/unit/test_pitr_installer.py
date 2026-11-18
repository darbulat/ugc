"""Protect pinned installer assets and bounded extraction."""

import hashlib
import importlib
import io
import tarfile
from pathlib import Path

import pytest


@pytest.fixture
def operator(monkeypatch):
    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[2] / "scripts")
    )
    return importlib.import_module("pitr_operator")


def test_download_rejects_more_than_the_explicit_limit(operator, monkeypatch):
    monkeypatch.setattr(
        operator.urllib.request,
        "urlopen",
        lambda *args, **kwargs: io.BytesIO(b"123456789"),
    )
    with pytest.raises(ValueError, match="size limit"):
        operator.download("https://fixture.invalid/asset", 8)


@pytest.mark.parametrize("kind", [tarfile.SYMTYPE, tarfile.LNKTYPE])
def test_selected_binary_must_be_a_regular_file(operator, monkeypatch, kind):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        entry = tarfile.TarInfo("age/age")
        entry.type = kind
        entry.linkname = "/outside/neighbor-project"
        archive.addfile(entry)
    data = buffer.getvalue()
    monkeypatch.setattr(operator, "download", lambda *args: data)
    monkeypatch.setattr(operator, "AGE_SHA", hashlib.sha256(data).hexdigest())
    with pytest.raises(ValueError, match="Unsafe"):
        operator.age_binaries()


def test_checksum_is_checked_before_archive_parsing(operator, monkeypatch):
    monkeypatch.setattr(operator, "download", lambda *args: b"not an archive")
    with pytest.raises(ValueError, match="checksum"):
        operator.age_binaries()


def test_empty_binary_is_rejected_even_in_a_valid_archive(
    operator, monkeypatch
):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        archive.addfile(tarfile.TarInfo("age/age"), io.BytesIO())
    data = buffer.getvalue()
    monkeypatch.setattr(operator, "download", lambda *args: data)
    monkeypatch.setattr(operator, "AGE_SHA", hashlib.sha256(data).hexdigest())
    with pytest.raises(ValueError, match="oversized"):
        operator.age_binaries()
