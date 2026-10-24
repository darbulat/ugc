"""Portable real old P01 producer; synthetic local test facts only."""

import builtins
import json
from hashlib import sha256
from pathlib import Path
from types import ModuleType

from sqlalchemy import select
from sqlalchemy.orm import Session

from ugc_bot.infrastructure.db.payout_models import TABLE_MAP

FIXTURE = Path(__file__).parents[1] / "fixtures/physical_proofs/pre_cutover"


def pre_cutover_factory():
    """Execute hash-verified archived bytes with local import substitution.

    No global module monkeypatch, temporary-file dependency, generated owner
    identity or altered producer code participates in historical production.
    """
    manifest = json.loads((FIXTURE / "manifest.json").read_text())
    modules = {}
    for row in manifest["files"]:
        source = (FIXTURE / row["fixture_file"]).read_bytes()
        assert len(source) == row["bytes"]
        assert sha256(source).hexdigest() == row["sha256"]
        name = row["source_path"][4:-3].replace("/", ".")
        module = ModuleType("portable_pre_cutover." + name)
        module.__file__ = str(FIXTURE / row["fixture_file"])

        def importing(name, *args, **kwargs):
            return modules.get(name) or builtins.__import__(
                name, *args, **kwargs
            )

        module.__dict__["__builtins__"] = vars(builtins) | {
            "__import__": importing
        }
        exec(compile(source, module.__file__, "exec"), module.__dict__)
        modules[name] = module
    return modules["ugc_bot.container.payout_factory"].build_payout_service


def payout_facts(engine):
    """Immutable actual receipts, bank evidence and monetary links."""
    with Session(engine) as db:
        return {
            name: tuple(
                dict(row)
                for row in db.execute(select(TABLE_MAP[name])).mappings().all()
            )
            for name in (
                "commands",
                "outcomes",
                "settlements",
                "intents",
                "events",
            )
        }
