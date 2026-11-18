"""Protect operational settings and peers during a CI image rollout."""

import copy
import hashlib
import json
import os
import runpy
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def release_module():
    source = (
        Path(__file__).resolve().parents[2] / "scripts/production_release.py"
    )
    return runpy.run_path(str(source))


@pytest.fixture
def live_restore_module():
    source = (
        Path(__file__).resolve().parents[2]
        / "scripts/configure_live_restore.py"
    )
    return runpy.run_path(str(source))


def test_interpolation_preserves_passwords_and_shell_variables(release_module):
    escape = release_module["escape_interpolation"]
    settings = {
        "environment": {"TOKEN": "a$b${HOME}$$"},
        "command": ["sh", "-c", "echo $READY"],
        "replicas": 2,
    }
    original = copy.deepcopy(settings)
    encoded = escape(settings)
    assert encoded["environment"]["TOKEN"] == "a$$b$${HOME}$$$$"
    assert encoded["command"][2] == "echo $$READY"
    assert encoded["replicas"] == 2
    assert settings == original


def test_compose_serialized_settings_preserve_literal_dollars(
    release_module,
):
    decoded = release_module["unescape_interpolation"](
        {
            "entrypoint": None,
            "command": ["sh", "-c", "echo $$READY $$$$"],
            "environment": {"TOKEN": "literal$$$$value"},
            "healthcheck": {"test": ["CMD-SHELL", "test $$READY"]},
        }
    )
    assert decoded["entrypoint"] is None
    assert decoded["command"] == ["sh", "-c", "echo $READY $$"]
    assert decoded["healthcheck"]["test"] == ["CMD-SHELL", "test $READY"]
    assert decoded["environment"]["TOKEN"] == "literal$$value"


def test_only_service_defaults_are_removed_during_normalization(release_module):
    model = {
        "services": {
            "app": {
                "entrypoint": None,
                "environment": {"command": None},
            }
        }
    }
    result = release_module["normalized_services"](model)
    assert "entrypoint" not in result["app"]
    assert result["app"]["environment"] == {"command": None}


def test_private_configuration_is_exclusive_and_owner_only(
    release_module, tmp_path
):
    target = tmp_path / "compose.json"
    release_module["private_json"](
        target, {"environment": {"TOKEN": "private"}}
    )
    assert target.stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        release_module["private_json"](target, {})


def test_archive_verification_detects_tampering(release_module, tmp_path):
    archive = tmp_path / "image.tar.gz"
    archive.write_bytes(b"verified CI artifact")
    manifest = {
        "revision": "a" * 40,
        "image_id": "sha256:" + "b" * 64,
        "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    verify = release_module["verify_archive"]
    assert verify(tmp_path) == manifest
    archive.write_bytes(b"changed artifact")
    with pytest.raises(ValueError, match="checksum"):
        verify(tmp_path)


@pytest.mark.parametrize(
    "field,value", [("revision", "main"), ("image_id", "latest")]
)
def test_archive_requires_immutable_identifiers(
    release_module, tmp_path, field, value
):
    manifest = {"revision": "a" * 40, "image_id": "sha256:" + "b" * 64}
    manifest[field] = value
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="Invalid"):
        release_module["verify_archive"](tmp_path)


def test_snapshot_validation_precedes_writing_secrets(
    release_module, tmp_path, monkeypatch
):
    write = release_module["write_snapshot"]
    monkeypatch.setitem(
        write.__globals__, "checked", lambda *a, **kw: '{"services":{}}'
    )
    with pytest.raises(RuntimeError, match="round-trip"):
        write(
            tmp_path / "compose.json",
            {"services": {"app": {"image": "sha256:old"}}},
        )
    assert list(tmp_path.iterdir()) == []


def test_live_restore_preserves_existing_settings_and_reloads(
    live_restore_module, tmp_path, monkeypatch
):
    configure = live_restore_module["configure"]
    path = tmp_path / "daemon.json"
    settings = {
        "log-driver": "local",
        "features": {"containerd-snapshotter": True},
    }
    path.write_text(json.dumps(settings))
    validated = []

    def validate(command, **kwargs):
        pending = Path(command[-1])
        validated.append(json.loads(pending.read_text()))
        return SimpleNamespace(returncode=0)

    signals = []
    monkeypatch.setattr(configure.__globals__["subprocess"], "run", validate)
    monkeypatch.setattr(os, "kill", lambda pid, sig: signals.append((pid, sig)))
    assert configure(path, Path("dockerd"), 1234) is True
    assert validated == [settings | {"live-restore": True}]
    assert json.loads(path.read_text()) == validated[0]
    assert len(signals) == 1 and signals[0][0] == 1234
    assert path.stat().st_mode & 0o777 == 0o600
    backup = path.with_name("daemon.json.before-live-restore")
    assert json.loads(backup.read_text()) == settings
    assert set(tmp_path.iterdir()) == {path, backup}


def test_live_restore_validation_failure_preserves_file(
    live_restore_module, tmp_path, monkeypatch
):
    configure = live_restore_module["configure"]
    path = tmp_path / "daemon.json"
    previous = b'{"log-driver":"local"}\n'
    path.write_bytes(previous)
    monkeypatch.setattr(
        configure.__globals__["subprocess"],
        "run",
        lambda *a, **kw: SimpleNamespace(returncode=1),
    )
    with pytest.raises(RuntimeError, match="validation"):
        configure(path, Path("dockerd"), 1234)
    assert path.read_bytes() == previous
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("exists", [False, True])
def test_live_restore_restores_file_if_signal_fails(
    live_restore_module, tmp_path, monkeypatch, exists
):
    configure = live_restore_module["configure"]
    path = tmp_path / "daemon.json"
    previous = b'{"log-driver":"local"}\n'
    if exists:
        path.write_bytes(previous)
    monkeypatch.setattr(
        configure.__globals__["subprocess"],
        "run",
        lambda *a, **kw: SimpleNamespace(returncode=0),
    )

    def denied(*args):
        raise PermissionError("denied")

    monkeypatch.setattr(os, "kill", denied)
    with pytest.raises(PermissionError):
        configure(path, Path("dockerd"), 1234)
    assert path.exists() == exists
    if exists:
        assert path.read_bytes() == previous


def test_live_restore_refuses_concurrent_changes(
    live_restore_module, tmp_path, monkeypatch
):
    configure = live_restore_module["configure"]
    path = tmp_path / "daemon.json"
    path.write_text("{}")

    def validate(*args, **kwargs):
        path.write_text('{"log-driver":"local"}')
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(configure.__globals__["subprocess"], "run", validate)
    with pytest.raises(RuntimeError, match="changed"):
        configure(path, Path("dockerd"), 1234)
    assert json.loads(path.read_text()) == {"log-driver": "local"}


def test_live_restore_reloads_existing_configuration(
    live_restore_module, tmp_path, monkeypatch
):
    path = tmp_path / "daemon.json"
    path.write_text('{"live-restore":true}')
    configure = live_restore_module["configure"]
    signals = []
    monkeypatch.setattr(
        configure.__globals__["subprocess"],
        "run",
        lambda *a, **kw: SimpleNamespace(returncode=0),
    )
    monkeypatch.setattr(os, "kill", lambda *args: signals.append(args))
    assert configure(path, Path("dockerd"), 1234) is False
    assert len(signals) == 1
    assert path.read_text() == '{"live-restore":true}'


@pytest.mark.parametrize("as_list", [False, True])
def test_old_rollout_placeholders_preserve_live_values(
    release_module, tmp_path, as_list
):
    source = tmp_path / "old-compose.json"
    placeholder = "${UGC_ROLLOUT_SECRET_17:?required}"
    source.write_text(placeholder)
    values = {"PRIVATE_KEY": placeholder, "INTERVAL": 24, "OPTIONAL": None}
    if as_list:
        values = ["PRIVATE_KEY=" + placeholder, "OPTIONAL"]
    model = {"services": {"app": {"environment": values}}}
    result = release_module["rollout_environment"](
        model, "app", [source], {"PRIVATE_KEY": "literal$private"}
    )
    assert result["UGC_ROLLOUT_SECRET_17"] == "literal$private"


def test_old_rollout_unresolved_placeholder_blocks_release(
    release_module, tmp_path
):
    source = tmp_path / "old-compose.json"
    source.write_text("${UGC_ROLLOUT_MISSING:?required}")
    model = {"services": {"app": {"environment": {}}}}
    with pytest.raises(RuntimeError, match="Unresolved"):
        release_module["rollout_environment"](model, "app", [source], {})


def fake_container(service, image="old"):
    return {
        "Id": "container-" + service,
        "Image": image,
        "Config": {"Env": ["SECRET=unchanged"]},
        "HostConfig": {},
        "Mounts": [],
        "NetworkSettings": {"Networks": {"ugc_default": {}}},
    }


def test_partial_rollout_failure_restores_every_attempted_service(
    release_module, tmp_path, monkeypatch
):
    deploy = release_module["deploy_services"]
    state = {name: fake_container(name) for name in ("app", "app_2")}
    signature = release_module["runtime_signature"]
    previous = {
        service: {
            "image_id": item["Image"],
            "container_id": item["Id"],
            "signature": signature(item),
        }
        for service, item in state.items()
    }
    commands = []

    def checked(command, **kwargs):
        service = command[-1]
        commands.append(service)
        old = "previous-compose.json" in " ".join(command)
        state[service] = fake_container(service, "old" if old else "new")

    def wait_ready(service, image_id, **kwargs):
        if service == "app_2" and image_id == "new":
            raise RuntimeError("New replica unavailable")

    globals_ = deploy.__globals__
    monkeypatch.setitem(globals_, "inspect", lambda name: state[name[4:-2]])
    monkeypatch.setitem(globals_, "checked", checked)
    monkeypatch.setitem(globals_, "wait_ready", wait_ready)
    monkeypatch.setitem(globals_, "webhook_on_peer", lambda service: None)
    monkeypatch.setitem(globals_, "reload_nginx", lambda: None)
    monkeypatch.setitem(globals_, "public_smoke", lambda: None)
    with pytest.raises(RuntimeError, match="New replica"):
        deploy(tmp_path, ["app", "app_2"], previous, "new")
    assert commands == ["app", "app_2", "app_2", "app"]
    assert all(item["Image"] == "old" for item in state.values())


def test_unhealthy_peer_prevents_container_replacement(
    release_module, tmp_path, monkeypatch
):
    deploy = release_module["deploy_services"]
    globals_ = deploy.__globals__
    current = fake_container("app")
    monkeypatch.setitem(globals_, "inspect", lambda name: current)
    operations = []
    monkeypatch.setitem(
        globals_, "checked", lambda *a, **kw: operations.append(a)
    )

    def unhealthy(*args):
        raise RuntimeError("Peer unavailable")

    monkeypatch.setitem(globals_, "wait_ready", unhealthy)
    with pytest.raises(RuntimeError, match="Peer unavailable"):
        deploy(
            tmp_path, ["app"], {"app": {"container_id": current["Id"]}}, "new"
        )
    assert operations == []
