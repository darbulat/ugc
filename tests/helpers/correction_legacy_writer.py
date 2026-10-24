"""Exact archived correction writer for genuine old-head compatibility tests.

This loader imports definitions only. Callers own the database, transactions,
principals and genuine inputs; loading alone proves no SQL compatibility.
Keep the context open while using its archived command classes and writers.
"""

import builtins
import hashlib
import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from uuid import uuid4

_IMPORT = builtins.__import__
_ROOT = Path(__file__).resolve().parents[2]
_ARCHIVE = _ROOT / "tests/fixtures/corrections/pre_approval_binding"
_MANIFEST_HASH = (
    "a082d2a751f542c5c0a9823e4572e35d573d3479c0c777aa3a2b3915c1993acb"
)
_FILES = (
    ("ports", "correction_ports.py.source"),
    ("service", "correction_service.py.source"),
    ("repository", "corrections_repository.py.source"),
)


@dataclass(frozen=True, slots=True)
class ArchivedCorrectionWriter:
    ports: ModuleType
    service: ModuleType
    repository: ModuleType


def _checked_bytes(path: Path, digest: str) -> bytes:
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != digest:
        raise ValueError(f"archived_correction_integrity:{path.name}")
    return content


def _validated_sources(archive: Path, root: Path) -> dict[str, bytes]:
    manifest = json.loads(
        _checked_bytes(archive / "manifest.json", _MANIFEST_HASH)
    )
    sources = {
        entry["archive_file"]: _checked_bytes(
            archive / entry["archive_file"], entry["sha256"]
        )
        for entry in manifest["source_files"]
    }
    for relative, digest in manifest["unchanged_dependencies_sha256"].items():
        _checked_bytes(root / relative, digest)
    return sources


@contextmanager
def archived_correction_writer(
    *, archive_dir: Path | None = None, repository_root: Path | None = None
) -> Iterator[ArchivedCorrectionWriter]:
    """Load the pinned three-module writer, without canonical module aliases.

    Explicit paths support isolated copied-fixture integrity checks. They do
    not change the pinned manifest or allow a different historical writer.
    """
    archive = _ARCHIVE if archive_dir is None else archive_dir
    root = _ROOT if repository_root is None else repository_root
    sources = _validated_sources(archive, root)
    prefix = f"_ugc_archived_correction_{uuid4().hex}_"
    modules: dict[str, ModuleType] = {}

    def archived_import(name, globals=None, locals=None, fromlist=(), level=0):
        if level == 0 and name == "ugc_bot.application.correction_ports":
            return modules["ports"]
        return _IMPORT(name, globals, locals, fromlist, level)

    try:
        for key, filename in _FILES:
            module = ModuleType(prefix + key)
            module.__file__ = str(archive / filename)
            module.__package__ = ""
            module.__dict__["__builtins__"] = dict(
                vars(builtins), __import__=archived_import
            )
            modules[key] = module
            # Dataclass postponed annotations require this private key during
            # decoration and through the caller's use of the archived classes.
            sys.modules[module.__name__] = module
            exec(
                compile(sources[filename], module.__file__, "exec"),
                module.__dict__,
            )
        yield ArchivedCorrectionWriter(**modules)
    finally:
        for module in modules.values():
            sys.modules.pop(module.__name__, None)
