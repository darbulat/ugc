"""Exercise the reserve installer with the real pinned age bundle."""

import io
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts"))
import pitr_operator as operator  # noqa: E402


def main():
    archive = Path(sys.argv[1]).read_bytes()
    assert 16 * 1024**2 < len(archive) < 32 * 1024**2
    revision = "f" * 40
    commands = []
    created = False
    corrupted = True
    with tempfile.TemporaryDirectory(prefix="pitr-install-check-") as work:
        host = Path(work)
        operator.ROOT = host / "opt"
        operator.ETC = host / "etc"
        operator.STATE = host / "state"
        operator.RESTORE = host / "restore"
        operator.UNIT_ROOT = host / "units"
        operator.UNIT_ROOT.mkdir()
        release = operator.ROOT / "releases" / revision
        release.mkdir(parents=True)
        for name in ("pitr_operator.py", "pitr_store.py"):
            (release / name).write_bytes((REPO / "scripts" / name).read_bytes())
        operator.__file__ = str(release / "pitr_operator.py")
        baseline = {
            "existing-video-worker": {"MainPID": "123", "ActiveState": "active"}
        }
        operator.neighbors = lambda: baseline.copy()

        def account(name):
            if not created:
                raise KeyError(name)
            return SimpleNamespace(pw_uid=os.getuid(), pw_gid=os.getgid())

        operator.pwd.getpwnam = account

        def response(url, timeout):
            if url == operator.AGE_URL:
                return io.BytesIO(archive + b"tamper" if corrupted else archive)
            prefix = (
                f"https://raw.githubusercontent.com/darbulat/ugc/{revision}/"
            )
            assert url.startswith(prefix)
            return io.BytesIO((REPO / url.removeprefix(prefix)).read_bytes())

        operator.urllib.request.urlopen = response
        native_run = operator.run

        def platform_run(command, **kwargs):
            nonlocal created
            if command[0] == "/usr/sbin/useradd":
                commands.append(command)
                assert command[-1] == "ugc-pitr"
                created = True
                return ""
            if command[0] == "/usr/bin/systemctl":
                assert command == ["/usr/bin/systemctl", "daemon-reload"]
                commands.append(command)
                return ""
            if command[0] == "/usr/bin/ssh-keygen":
                commands.append(command)
                target = Path(command[command.index("-f") + 1])
                assert target.parent == operator.ETC
                operator.private_file(target, b"synthetic-fixture-only")
                operator.private_file(
                    Path(str(target) + ".pub"),
                    b"ssh-ed25519 AAAAFIXTURE installer-test\n",
                )
                return ""
            assert Path(command[0]).parent == operator.ROOT / "bin"
            return native_run(command, **kwargs)

        operator.run = platform_run
        payload = {
            "revision": revision,
            "known_hosts": "primary ssh-ed25519 AAAAFIXTURE\n",
        }
        try:
            operator.install(payload)
        except ValueError as error:
            assert "checksum" in str(error)
        else:
            raise AssertionError("Tampered bundle was accepted")
        assert not commands, "Invalid assets must not create users or units"
        assert not operator.ETC.exists()
        corrupted = False
        result = operator.install(payload)
        assert result["revision"] == revision
        assert result["recipient"].startswith("age1")
        assert len(list(operator.UNIT_ROOT.iterdir())) == len(operator.UNITS)
        assert (operator.ETC / "pitr.identity").stat().st_mode & 0o777 == 0o600
        assert (operator.ROOT / "bin").stat().st_mode & 0o777 == 0o755
        version = native_run([str(operator.ROOT / "bin/age"), "--version"])
        assert "1.3.2" in version
        installed = json.loads((operator.ETC / "installed.json").read_text())
        assert installed["baseline"] == baseline
        print(
            json.dumps(
                {
                    "installer_completed": True,
                    "actual_age_archive_bytes": len(archive),
                    "age_version": version,
                    "invalid_asset_caused_no_host_changes": True,
                    "only_fixture_host_paths_modified": True,
                }
            )
        )


if __name__ == "__main__":
    os.umask(0o077)
    main()
