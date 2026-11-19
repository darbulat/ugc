"""Exercise encrypted streaming, archive integrity and S3 retention."""

import hashlib
import io
import json
import os
import runpy
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def bundle_module():
    return runpy.run_path(
        str(Path(__file__).resolve().parents[2] / "scripts/recovery_bundle.py")
    )


@pytest.fixture
def backup_module(monkeypatch):
    scripts = Path(__file__).resolve().parents[2] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    return runpy.run_path(str(scripts / "backup_recovery.py"))


@pytest.fixture
def age_identity(tmp_path):
    binary = os.environ.get("AGE_BINARY") or shutil.which("age")
    if not binary:
        pytest.skip("age encryption is exercised by the dedicated CI job")
    age = Path(binary)
    identity = tmp_path / "identity.txt"
    keygen = age.parent / "age-keygen"
    subprocess.run(
        [str(keygen), "-o", str(identity)], capture_output=True, check=True
    )
    recipient = subprocess.check_output(
        [str(keygen), "-y", str(identity)],
        text=True,
    ).strip()
    return age, identity, recipient


def test_encrypted_bundle_round_trip_covers_files_and_configuration(
    bundle_module, age_identity, tmp_path
):
    age, identity, recipient = age_identity
    source = tmp_path / "project"
    source.mkdir()
    secret = b"TOKEN=synthetic$private-value\n"
    (source / ".env").write_bytes(secret)
    (source / "link").symlink_to(".env")
    os.link(source / ".env", source / "second.env")
    encrypted = tmp_path / "recovery.age"
    with encrypted.open("wb") as output:
        manifest = bundle_module["create_bundle"](
            age,
            recipient,
            [{"path": str(source), "name": "project"}],
            {"configuration/compose.json": '{"services":{}}'},
            output,
        )
    assert secret not in encrypted.read_bytes()
    decoded = subprocess.check_output(
        [str(age), "--decrypt", "--identity", str(identity), str(encrypted)]
    )
    with tarfile.open(fileobj=io.BytesIO(decoded), mode="r:gz") as archive:
        saved = json.load(archive.extractfile("manifest.json"))
        assert saved == manifest
        assert archive.extractfile("project/.env").read() == secret
        assert saved["project/link"] == {"symlink": ".env"}
        assert saved["project/second.env"] == {"hardlink": "project/.env"}
        for name, entry in saved.items():
            if "sha256" in entry:
                payload = archive.extractfile(name).read()
                assert len(payload) == entry["size"]
                assert hashlib.sha256(payload).hexdigest() == entry["sha256"]
    assert identity.stat().st_mode & 0o777 == 0o600


def test_tampered_ciphertext_fails_authentication(
    bundle_module, age_identity, tmp_path
):
    age, identity, recipient = age_identity
    encrypted = tmp_path / "recovery.age"
    with encrypted.open("wb") as output:
        bundle_module["create_bundle"](
            age, recipient, [], {"configuration/test": "data" * 200}, output
        )
    payload = bytearray(encrypted.read_bytes())
    payload[-12] ^= 1
    encrypted.write_bytes(payload)
    result = subprocess.run(
        [str(age), "--decrypt", "--identity", str(identity), str(encrypted)],
        capture_output=True,
    )
    assert result.returncode != 0


@pytest.mark.parametrize(
    "name", ["", "/absolute", "../escape", "data/../escape"]
)
def test_archive_rejects_unsafe_names(bundle_module, name):
    with pytest.raises(ValueError, match="Invalid"):
        bundle_module["validate_name"](name)


def test_archive_rejects_external_symlink(bundle_module, tmp_path):
    source = tmp_path / "link"
    source.symlink_to("/etc/passwd")
    with (
        tarfile.open(fileobj=io.BytesIO(), mode="w") as archive,
        pytest.raises(ValueError, match="outside"),
    ):
        bundle_module["add_path"](archive, source, "project/link", {})


def test_duplicate_member_cannot_hide_an_earlier_file(bundle_module):
    with (
        tarfile.open(fileobj=io.BytesIO(), mode="w") as archive,
        pytest.raises(ValueError, match="Duplicate"),
    ):
        bundle_module["add_memory"](
            archive, "project/.env", "changed", {"project/.env": {}}
        )


def test_bundle_plan_includes_configuration_assets_and_certificates(
    backup_module,
):
    snapshot = {"services": {"app": {"environment": {"TOKEN": "a$b"}}}}
    plan = backup_module["recovery_plan"](snapshot, "age1synthetic")
    sources = {item["name"] for item in plan["sources"]}
    assert {
        "project/.env",
        "project/config",
        "project/nginx",
        "backup/timeweb.json",
        "order-images",
        "certificates",
        "operations/production_release.py",
        "operations/apply_resource_policy.py",
        "operations/production-resource-policy.json",
        "operations/backup_recovery.py",
        "operations/snapshot-environment.json",
        "operations/installed.json",
        "operations/bin/age",
        "release-manifest.json",
    } <= sources
    config = json.loads(plan["memory"]["configuration/compose.json"])
    assert config["services"]["app"]["environment"]["TOKEN"] == "a$$b"
    assert all("downloaded" not in item for item in sources)
    assert all("identity.txt" not in item for item in sources)
    assert all("recovery-archives" not in item for item in sources)


def test_removed_historical_image_is_recorded_without_inventing_a_digest(
    backup_module, monkeypatch
):
    inventory = backup_module["image_inventory"]

    def missing(*args):
        raise RuntimeError("Image no longer available")

    monkeypatch.setitem(inventory.__globals__, "inspect", missing)
    old = {
        "Image": "sha256:historical",
        "State": {"Status": "exited"},
        "Config": {"Image": "ugc-migrate"},
    }
    assert inventory([old]) == {
        "sha256:historical": {
            "tags": None,
            "digests": None,
            "revision": None,
            "metadata_available": False,
            "configured_references": ["ugc-migrate"],
        }
    }


def test_active_image_lookup_failure_still_blocks_backup(
    backup_module, monkeypatch
):
    inventory = backup_module["image_inventory"]

    def missing(*args):
        raise RuntimeError("Active image unavailable")

    monkeypatch.setitem(inventory.__globals__, "inspect", missing)
    stopped = {
        "Image": "sha256:shared",
        "State": {"Status": "exited"},
        "Config": {"Image": "old-job"},
    }
    running = stopped | {
        "State": {"Status": "running"},
        "Config": {"Image": "active-service"},
    }
    with pytest.raises(RuntimeError, match="Active image"):
        inventory([stopped, running])


def test_available_images_keep_verified_metadata_and_each_reference(
    backup_module, monkeypatch
):
    inventory = backup_module["image_inventory"]
    details = {
        "RepoTags": ["repo:release"],
        "RepoDigests": ["repo@sha256:verified"],
        "Config": {"Labels": {"org.opencontainers.image.revision": "abc"}},
    }
    monkeypatch.setitem(inventory.__globals__, "inspect", lambda *a: details)
    first = {
        "Image": "sha256:current",
        "State": {"Status": "running"},
        "Config": {"Image": "repo:release"},
    }
    second = first | {"Config": {"Image": "sha256:current"}}
    result = inventory([first, second, first])["sha256:current"]
    assert result["metadata_available"] is True
    assert result["digests"] == details["RepoDigests"]
    assert result["revision"] == "abc"
    assert result["configured_references"] == ["repo:release", "sha256:current"]


@pytest.fixture
def upload_environment(backup_module, monkeypatch, tmp_path):
    path = tmp_path / "ugc-recovery-test.tar.gz.age"
    path.write_bytes(b"encrypted fixture")
    old = datetime.now(timezone.utc) - timedelta(days=8)
    items = [
        {
            "Key": "recovery/ugc-recovery-old.tar.gz.age",
            "Size": 20,
            "LastModified": old,
        },
        {"Key": "database/old.sql.gz", "Size": 20, "LastModified": old},
    ]
    deleted = []
    verified = []
    client = SimpleNamespace(
        get_paginator=lambda _: SimpleNamespace(
            paginate=lambda **kw: [{"Contents": items}]
        ),
        head_object=lambda **kw: {"ContentLength": path.stat().st_size},
        delete_object=lambda **kw: deleted.append(kw["Key"]),
    )
    import boto3

    monkeypatch.setattr(boto3, "client", lambda *a, **kw: client)
    monkeypatch.setitem(
        sys.modules,
        "backup_db",
        SimpleNamespace(
            _get_s3_config=lambda: {
                "endpoint_url": "https://synthetic.invalid",
                "bucket": "test",
                "access_key": "test",
                "secret_key": "test",
            },
        ),
    )
    verifier = SimpleNamespace(
        verified_upload=lambda *a: verified.append(a) or True
    )
    monkeypatch.setitem(sys.modules, "s3_verified", verifier)
    monkeypatch.setattr(sys, "argv", ["uploader", str(path)])
    return backup_module["UPLOADER"], items, deleted, verified, verifier, client


def test_verified_upload_only_prunes_recovery_objects(upload_environment):
    program, items, deleted, verified, verifier, client = upload_environment
    exec(program, {})
    assert len(verified) == 1
    assert deleted == ["recovery/ugc-recovery-old.tar.gz.age"]


def test_failed_upload_preserves_all_remote_objects(upload_environment):
    program, items, deleted, verified, verifier, client = upload_environment
    verifier.verified_upload = lambda *a: False
    with pytest.raises(SystemExit, match="verification"):
        exec(program, {})
    assert deleted == []


def test_capacity_limit_blocks_upload_before_remote_mutation(
    upload_environment,
):
    program, items, deleted, verified, verifier, client = upload_environment
    items[0]["Size"] = 10_000_000_000
    with pytest.raises(SystemExit, match="capacity"):
        exec(program, {})
    assert verified == [] and deleted == []


def test_remote_size_mismatch_preserves_retention_history(upload_environment):
    program, items, deleted, verified, verifier, client = upload_environment
    client.head_object = lambda **kwargs: {"ContentLength": 0}
    with pytest.raises(SystemExit, match="size mismatch"):
        exec(program, {})
    assert deleted == []


def test_existing_ciphertext_survives_retry(
    backup_module, tmp_path, monkeypatch
):
    create = backup_module["create_local_bundle"]
    globals_ = create.__globals__
    monkeypatch.setitem(globals_, "checked", lambda *a, **kw: "[]")
    monkeypatch.setitem(globals_, "live_snapshot", lambda _: {})
    output = tmp_path / "existing.age"
    output.write_bytes(b"previous verified ciphertext")
    with pytest.raises(FileExistsError):
        create(output, "image", tmp_path / "age", "age1synthetic")
    assert output.read_bytes() == b"previous verified ciphertext"


def test_failed_producer_cleans_partial_ciphertext_and_container(
    backup_module, tmp_path, monkeypatch
):
    create = backup_module["create_local_bundle"]
    globals_ = create.__globals__
    monkeypatch.setitem(globals_, "checked", lambda *a, **kw: "[]")
    monkeypatch.setitem(globals_, "live_snapshot", lambda _: {})
    operations = []

    def operation(command, **kwargs):
        operations.append(command)
        if command[1] == "run":
            kwargs["stdout"].write(b"partial ciphertext")
            return SimpleNamespace(returncode=1)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(globals_["subprocess"], "run", operation)
    output = tmp_path / "failed.age"
    with pytest.raises(RuntimeError, match="creation failed"):
        create(output, "image", tmp_path / "age", "age1synthetic")
    assert not output.exists()
    assert operations[-1][:3] == ["docker", "rm", "-f"]
    assert operations[-1][-1].startswith("ugc-recovery-")


@pytest.fixture
def backup_cli(backup_module, tmp_path, monkeypatch):
    main = backup_module["main"]
    parameters = {
        "META_TOKEN_MONITOR_IMAGE": "synthetic-monitor:checked",
        "META_TOKEN_MONITOR_SETTINGS_DIR": "/private/synthetic/settings",
        "META_TOKEN_MONITOR_STATE_DIR": "/private/synthetic/state",
        "META_TOKEN_MONITOR_UID": "1000",
        "META_TOKEN_MONITOR_GID": "1000",
    }
    source = tmp_path / "snapshot-environment.json"
    source.write_text(json.dumps(parameters))
    source.chmod(0o600)
    loader = main.__globals__["load_snapshot_environment"]
    monkeypatch.setitem(loader.__globals__, "SNAPSHOT_ENVIRONMENT", source)
    for name in parameters:
        monkeypatch.setenv(name, "not-loaded")
    recipient = tmp_path / "recipient.txt"
    recipient.write_text("age1synthetic")
    output = tmp_path / "archives"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "backup_recovery.py",
            "--recipient",
            str(recipient),
            "--age",
            str(tmp_path / "age"),
            "--image",
            "checked-image",
            "--output-directory",
            str(output),
        ],
    )
    monkeypatch.setitem(
        main.__globals__,
        "open_lock",
        lambda path: (tmp_path / Path(path).name).open("a+"),
    )
    return main, source, parameters, output


def test_backup_cli_loads_private_parameters_for_snapshot_and_upload(
    backup_cli, monkeypatch, capsys
):
    main, _, parameters, output = backup_cli
    created = []
    monkeypatch.setitem(
        main.__globals__, "inspect", lambda *args: {"Id": "checked-image"}
    )

    def create(path, *args):
        assert {key: os.environ[key] for key in parameters} == parameters
        path.write_bytes(b"synthetic ciphertext")
        created.append(path)

    monkeypatch.setitem(main.__globals__, "create_local_bundle", create)
    monkeypatch.setitem(
        main.__globals__,
        "upload_bundle",
        lambda path: {
            "key": "recovery/" + path.name,
            "bytes": path.stat().st_size,
        },
    )
    main()
    assert len(created) == 1 and created[0].parent == output
    assert json.loads(capsys.readouterr().out)["bytes"] == len(
        b"synthetic ciphertext"
    )


def test_backup_rejects_public_parameter_file_before_any_backup_work(
    backup_cli, monkeypatch
):
    main, source, _, output = backup_cli
    source.chmod(0o644)

    def unexpected(*args):
        pytest.fail("Unsafe settings must fail before Docker or archive work")

    monkeypatch.setitem(main.__globals__, "inspect", unexpected)
    monkeypatch.setitem(main.__globals__, "create_local_bundle", unexpected)
    with pytest.raises(ValueError, match="owner-only"):
        main()
    assert not output.exists()
