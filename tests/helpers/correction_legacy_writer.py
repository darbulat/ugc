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
    ("domain", "domain_corrections.py.source"),
    ("ports", "correction_ports.py.source"),
    ("service", "correction_service.py.source"),
    ("repository", "corrections_repository.py.source"),
)
_ARCHIVED_DEPENDENCIES = {
    "src/ugc_bot/domain/corrections.py": "domain_corrections.py.source",
    "src/ugc_bot/infrastructure/db/correction_schema.py": (
        "correction_schema.py.source"
    ),
}


@dataclass(frozen=True, slots=True)
class ArchivedCorrectionWriter:
    domain: ModuleType
    ports: ModuleType
    service: ModuleType
    repository: ModuleType


def _checked_bytes(path: Path, digest: str) -> bytes:
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != digest:
        raise ValueError(f"archived_correction_integrity:{path.name}")
    return content


def _validated_sources(
    archive: Path, root: Path, *, archived_dependencies: bool
) -> dict[str, bytes]:
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
        filename = _ARCHIVED_DEPENDENCIES.get(relative)
        if archived_dependencies and filename:
            sources[filename] = _checked_bytes(archive / filename, digest)
        else:
            _checked_bytes(root / relative, digest)
    return sources


@contextmanager
def archived_correction_writer(
    *, archive_dir: Path | None = None, repository_root: Path | None = None
) -> Iterator[ArchivedCorrectionWriter]:
    """Load the pinned writer and its historical domain in private modules.

    Historical domain and schema dependencies are checked against the original
    manifest even when the current implementation has evolved. Explicit root
    paths retain strict validation for copied-fixture integrity checks.
    """
    archive = _ARCHIVE if archive_dir is None else archive_dir
    root = _ROOT if repository_root is None else repository_root
    sources = _validated_sources(
        archive, root, archived_dependencies=repository_root is None
    )
    prefix = f"_ugc_archived_correction_{uuid4().hex}_"
    modules: dict[str, ModuleType] = {}

    def archived_import(name, globals=None, locals=None, fromlist=(), level=0):
        if level == 0 and name == "ugc_bot.application.correction_ports":
            return modules["ports"]
        if level == 0 and name == "ugc_bot.domain.corrections":
            return modules["domain"]
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


def install_archived_correction_schema(engine) -> None:
    """Create the pinned old revision only in a fresh isolated test schema.

    The archived migration still calls its original table/trigger factories;
    substitute the hash-verified historical factory for this invocation only.
    Subsequent migrations run through the normal Alembic graph.
    """
    import re
    from types import FunctionType

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import text

    from tests.helpers.financial_environment import require_test_database
    from ugc_bot.infrastructure.db.migrations.versions import (
        financial_corrections_a1 as migration,
    )

    require_test_database(
        engine.url.set(query={}).render_as_string(hide_password=False)
    )
    sources = _validated_sources(_ARCHIVE, _ROOT, archived_dependencies=True)
    schema = ModuleType(f"_ugc_archived_correction_schema_{uuid4().hex}")
    schema.__file__ = str(_ARCHIVE / "correction_schema.py.source")
    exec(
        compile(
            sources["correction_schema.py.source"], schema.__file__, "exec"
        ),
        schema.__dict__,
    )
    scope = dict(migration.__dict__)
    scope["correction_tables"] = schema.correction_tables
    scope["correction_trigger_sql"] = schema.correction_trigger_sql
    scope["tables"] = FunctionType(migration.tables.__code__, scope)
    upgrade = FunctionType(migration.upgrade.__code__, scope)
    with engine.begin() as db:
        name = db.scalar(text("SELECT current_schema()"))
        revision = db.scalar(text("SELECT version_num FROM alembic_version"))
        if not re.fullmatch(r"financial_test_[a-f0-9]{32}", name or ""):
            raise ValueError("An isolated financial schema is required")
        if revision != migration.down_revision:
            raise ValueError("Expected the historical parent revision")
        with Operations.context(MigrationContext.configure(db)):
            upgrade()
        updated = db.execute(
            text(
                "UPDATE alembic_version SET version_num=:new "
                "WHERE version_num=:previous"
            ),
            {"new": migration.revision, "previous": migration.down_revision},
        )
        if updated.rowcount != 1:
            raise ValueError("Historical revision update failed")
