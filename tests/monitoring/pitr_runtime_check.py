"""Check the exact reserve rootfs installer against an empty public image."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import pitr_operator as operator  # noqa: E402


def main():
    original_mask = os.umask(0o077)
    try:
        with tempfile.TemporaryDirectory(prefix="pitr-runtime-check-") as work:
            root = Path(work)
            operator.ROOT = root / "opt"
            operator.ETC = root / "etc"
            operator.ROOT.mkdir()
            operator.ETC.mkdir()
            operator.pwd.getpwnam = lambda name: SimpleNamespace(
                pw_uid=998, pw_gid=998
            )
            operator.shutil.disk_usage = lambda path: SimpleNamespace(
                free=100 * 1024**3
            )
            with Path(sys.argv[1]).open("rb") as image:
                operator.sys.stdin = SimpleNamespace(buffer=image)
                result = operator.runtime({"image": operator.PG_IMAGE})
            runtime = operator.ROOT / "runtime"
            for path in [runtime, *runtime.rglob("*")]:
                if path.is_symlink():
                    assert path.resolve().is_relative_to(runtime)
                elif path.is_dir():
                    assert path.stat().st_mode & 0o005 == 0o005, path
                else:
                    assert not path.stat().st_mode & 0o6000, path
            assert (
                runtime / "usr/lib/postgresql/16/bin/postgres"
            ).stat().st_mode & 0o001
            assert "ugc-pitr:x:998:998:" in (runtime / "etc/passwd").read_text()
            assert not (runtime / "var/lib/postgresql/data/PG_VERSION").exists()
            assert (runtime / "dev").is_dir()
            version = subprocess.check_output(
                [
                    "chroot",
                    "--userspec=998:998",
                    str(runtime),
                    "/usr/lib/postgresql/16/bin/postgres",
                    "--version",
                ],
                text=True,
            )
            assert version.startswith("postgres (PostgreSQL) 16.")
            print(
                json.dumps(
                    result
                    | {
                        "public_directories_traversable": True,
                        "image_symlinks_confined": True,
                        "live_database_absent": True,
                        "unprivileged_postgres_executes": True,
                    }
                )
            )
    finally:
        os.umask(original_mask)


if __name__ == "__main__":
    main()
