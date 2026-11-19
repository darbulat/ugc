"""libpq credentials stay private despite systemd's group-readable mount."""

import importlib
import os
from pathlib import Path

import pytest


@pytest.fixture
def receiver(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[2] / "scripts")
    )
    credentials = tmp_path / "credentials"
    credentials.mkdir(mode=0o700)
    source = credentials / "pgpass"
    source.write_bytes(b"127.0.0.1:16543:*:ugc_pitr_v1:fixture-only\n")
    source.chmod(0o440)
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o700)
    monkeypatch.setenv("CREDENTIALS_DIRECTORY", str(credentials))
    monkeypatch.setenv("RUNTIME_DIRECTORY", str(runtime))
    original = os.umask(0o077)
    os.umask(original)
    try:
        yield importlib.import_module("pitr_receiver"), source, runtime
    finally:
        os.umask(original)


@pytest.mark.parametrize("failure", [False, True])
def test_private_copy_is_removed_on_success_and_failure(receiver, failure):
    module, source, runtime = receiver
    original = source.read_bytes()
    config = {
        "pg_host": "127.0.0.1",
        "pg_port": 16543,
        "pg_user": "ugc_pitr_v1",
    }
    private = None
    try:
        with module.private_pgpass(config) as authenticated:
            private = Path(authenticated["private_pgpass"])
            assert private.parent.parent == runtime
            assert private.parent.stat().st_mode & 0o777 == 0o700
            assert private.stat().st_mode & 0o777 == 0o600
            assert private.read_bytes() == original
            assert module.PostgreSQL(authenticated).environment()[
                "PGPASSFILE"
            ] == str(private)
            assert "private_pgpass" not in config
            if failure:
                raise RuntimeError("fixture failure")
    except RuntimeError:
        assert failure
    assert private is not None and not private.exists()
    assert not list(runtime.iterdir())
    assert source.read_bytes() == original
    assert source.stat().st_mode & 0o777 == 0o440


@pytest.mark.parametrize("size", [0, 4097])
def test_invalid_credential_size_leaves_no_private_copy(receiver, size):
    module, source, runtime = receiver
    source.chmod(0o600)
    source.write_bytes(b"x" * size)
    source.chmod(0o440)
    with (
        pytest.raises(ValueError, match="credential size"),
        module.private_pgpass({}),
    ):
        pytest.fail("Invalid credentials must not reach libpq")
    assert not list(runtime.iterdir())


@pytest.mark.parametrize(
    "action,function", [("receive", "run_receiver"), ("base", "create_base")]
)
def test_cli_uses_private_copy_and_cleans_it_after_failure(
    receiver, monkeypatch, action, function
):
    module, source, runtime = receiver
    observed = []

    def fail(config):
        private = Path(config["private_pgpass"])
        assert private != source
        assert private.stat().st_mode & 0o777 == 0o600
        observed.append(private)
        raise RuntimeError("fixture failure")

    monkeypatch.setattr(module, "load_config", lambda path: {})
    monkeypatch.setattr(module, function, fail)
    monkeypatch.setattr(
        module.sys, "argv", ["receiver", action, "--config", "fixture.json"]
    )
    with pytest.raises(RuntimeError, match="fixture failure"):
        module.main()
    assert observed and not observed[0].exists()
    assert not list(runtime.iterdir())
