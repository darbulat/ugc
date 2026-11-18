"""Keep dynamically loaded migration code inside the CI coverage scope."""

import importlib
import importlib.util
import os
import re
import sys
import tempfile
from pathlib import Path

import coverage


def main():
    workflow = (
        Path(__file__).resolve().parents[2] / ".github/workflows/lint-test.yml"
    )
    source = re.search(r"--cov=(\S+)", workflow.read_text())[1]
    previous = Path.cwd()
    with tempfile.TemporaryDirectory(prefix="coverage-dynamic-loader-") as work:
        root = Path(work).resolve()
        package = root / "src/ugc_bot"
        package.mkdir(parents=True)
        (package / "__init__.py").touch()
        migration = package / "migration_probe.py"
        migration.write_text(
            "VALUE = 1\ndef upgrade():\n    return VALUE + 1\n"
            "def downgrade():\n    return VALUE - 1\n"
        )
        sys.path.insert(0, str(root / "src"))
        os.chdir(root)
        collector = None
        try:
            importlib.import_module("ugc_bot")
            collector = coverage.Coverage(
                data_file=str(root / ".coverage"),
                config_file=False,
                source=[source],
            )
            collector.set_option("run:core", "sysmon")
            collector.start()
            spec = importlib.util.spec_from_file_location(
                "migration_loaded_by_alembic", migration
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            assert module.upgrade() == 2
            assert module.downgrade() == 0
            collector.stop()
            recorded = set(collector.get_data().lines(str(migration)) or [])
            assert {1, 2, 3, 4, 5} <= recorded, (
                "CI coverage omitted executed dynamically loaded migration code"
            )
            print("Dynamic migration coverage: all executed lines recorded")
        finally:
            if collector:
                collector.stop()
            os.chdir(previous)
            sys.path.remove(str(root / "src"))
            sys.modules.pop("ugc_bot", None)


if __name__ == "__main__":
    main()
