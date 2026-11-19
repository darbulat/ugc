"""Explicit test-only CLI; default action is a read-only inspection.

Run with python -m scripts.rehearse_test_residual_purge. Never reads .env or
DATABASE_URL. This release cannot write production, even with its credentials.
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

from sqlalchemy import create_engine

from scripts.residual_purge import (
    MANIFEST_PATH,
    delete_rehearsal,
    inspect_rehearsal,
    require_rehearsal_url,
    restore_rehearsal,
    validate_plan,
)
from scripts.residual_purge_catalog import UnsafePurge, digest, require


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--action", choices=("inspect", "delete", "restore"), default="inspect"
    )
    parser.add_argument("--schema", required=True)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    parser.add_argument("--manifest-sha256")
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--key-file", type=Path)
    args = parser.parse_args(argv)
    engine = None
    try:
        url = require_rehearsal_url(
            os.environ.get("PURGE_REHEARSAL_DATABASE_URL", "")
        )
        require(
            bool(re.fullmatch(r"financial_test_[a-f0-9]{32}", args.schema)),
            "isolated_schema_required",
        )
        plan = json.loads(args.manifest.read_text())
        validate_plan(plan)
        if args.action != "inspect":
            require(
                args.manifest_sha256 == digest(plan), "manifest_digest_required"
            )
            require(
                args.backup is not None and args.key_file is not None,
                "encrypted_backup_and_key_required",
            )
        url = url.update_query_dict(
            {"options": f"-csearch_path={args.schema},public"}
        )
        engine = create_engine(
            url,
            connect_args={"connect_timeout": 3},
            echo=False,
            hide_parameters=True,
        )
        if args.action == "inspect":
            result = inspect_rehearsal(engine, plan)
        elif args.action == "delete":
            result = delete_rehearsal(engine, plan, args.backup, args.key_file)
        else:
            result = restore_rehearsal(engine, plan, args.backup, args.key_file)
        print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:
        # SQL exceptions can include payloads/DSNs. Only our fixed codes escape.
        code = str(exc) if isinstance(exc, UnsafePurge) else "rehearsal_failed"
        print(
            json.dumps({"error": code, "production_writes_enabled": False}),
            file=sys.stderr,
        )
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
