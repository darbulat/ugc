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
    } <= sources
    config = json.loads(plan["memory"]["configuration/compose.json"])
    assert config["services"]["app"]["environment"]["TOKEN"] == "a$$b"
    assert all("downloaded" not in item for item in sources)


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
