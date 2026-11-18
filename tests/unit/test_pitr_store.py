"""Protect archive boundaries, recovery chains and retention dependencies."""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
from pitr_store import (  # noqa: E402
    BASE_NAME,
    Store,
    atomic_json,
    digest,
    lsn_number,
    safe_remove_tree,
    timestamp,
    wal_filename,
    wal_number,
)

RECIPIENT = "age1" + "q" * 58
SYSTEM = "7598122211340197923"


@pytest.fixture
def store(tmp_path):
    return Store(
        tmp_path / "archive", SYSTEM, "/not-used", [RECIPIENT], min_free_bytes=0
    )


def metadata(store, kind, stem, **kwargs):
    path = store.root / kind / (stem + ".age")
    path.write_bytes(b"encrypted fixture")
    result = {
        "artifact": path.name,
        "cipher_sha256": digest(path),
        "system_id": SYSTEM,
    } | kwargs
    atomic_json(path.with_suffix(".json"), result)
    return result


def base(store, index, finished, end="0/2000000"):
    return metadata(
        store,
        "base",
        f"base-20261118T12000{index}000000Z-abcdef01",
        finished_at=finished,
        timeline=1,
        end_lsn=end,
    )


def wal(store, number):
    name = wal_filename(1, number)
    return metadata(store, "wal", name, name=name, number=number, timeline=1)


def test_private_cluster_marker_cannot_adopt_foreign_data(tmp_path):
    root = tmp_path / "foreign"
    root.mkdir(mode=0o700)
    (root / "other-project").write_text("preserve")
    with pytest.raises(ValueError, match="existing"):
        Store(root, SYSTEM, "age", [RECIPIENT])
    assert (root / "other-project").read_text() == "preserve"


def test_cluster_identity_mismatch_preserves_archive(store):
    with pytest.raises(ValueError, match="another cluster"):
        Store(store.root, "1234567890123", "age", [RECIPIENT])
    assert json.loads((store.root / "cluster.json").read_text()) == {
        "system_id": SYSTEM
    }


@pytest.mark.parametrize(
    "name",
    ["../000000010000000000000001", "0" * 23, "000000010000000000000100"],
)
def test_invalid_wal_names_are_rejected(name):
    with pytest.raises(ValueError):
        wal_number(name)


def test_segment_index_handles_log_boundary():
    assert wal_filename(1, 256) == "000000010000000100000000"
    assert wal_number(wal_filename(2, 257)) == 257
    assert lsn_number("1/00000010") == 2**32 + 16


def test_recovery_time_must_have_timezone():
    with pytest.raises(ValueError, match="timezone"):
        timestamp("2026-11-18 12:00:00")
    assert timestamp("2026-11-18T15:00:00+03:00") == timestamp(
        "2026-11-18T12:00:00Z"
    )


def test_selects_base_before_target_not_latest(store):
    old = base(store, 1, "2026-11-18T10:00:00Z")
    base(store, 2, "2026-11-18T14:00:00Z")
    assert store.select_base("2026-11-18T12:00:00Z") == old
    with pytest.raises(ValueError, match="predates"):
        store.select_base("2026-11-18T09:00:00Z")


def test_missing_segment_breaks_chain(store):
    source = base(store, 1, "2026-11-18T10:00:00Z")
    wal(store, 2)
    wal(store, 4)
    with pytest.raises(ValueError, match="Gap"):
        store.wal_chain(source, "0/5000000")
    wal(store, 3)
    assert len(store.wal_chain(source, "0/5000000")) == 3


def test_other_timeline_cannot_fill_a_gap(store):
    source = base(store, 1, "2026-11-18T10:00:00Z")
    value = wal(store, 2)
    value["timeline"] = 2
    atomic_json(store.root / "wal" / (value["name"] + ".json"), value)
    with pytest.raises(ValueError, match="Gap"):
        store.wal_chain(source, "0/3000000")


def test_corrupt_ciphertext_is_not_usable(store):
    value = wal(store, 2)
    (store.root / "wal" / value["artifact"]).write_bytes(b"corrupted")
    with pytest.raises(ValueError, match="checksum"):
        store.check_artifact(value, "wal")


def test_artifact_path_traversal_is_rejected(store):
    with pytest.raises(ValueError, match="identity"):
        store.check_artifact(
            {"artifact": "../../other.age", "system_id": SYSTEM}, "wal"
        )


def test_retention_keeps_base_before_boundary_and_its_wal(store):
    base(store, 1, "2026-11-01T10:00:00Z", "0/1000000")
    boundary = base(store, 2, "2026-11-10T10:00:00Z", "0/2000000")
    latest = base(store, 3, "2026-11-17T10:00:00Z", "0/3000000")
    for index in range(1, 5):
        wal(store, index)
    now = datetime(2026, 11, 18, tzinfo=timezone.utc).timestamp()
    store.prune(now=now)
    assert store.metadata("base") == [boundary, latest]
    assert [w["number"] for w in store.metadata("wal")] == [2, 3, 4]


def test_capacity_never_prunes_a_chain_to_make_space(store):
    store.max_bytes = 1
    before = list(store.root.rglob("*"))
    with pytest.raises(RuntimeError, match="capacity"):
        store.capacity()
    assert list(store.root.rglob("*")) == before


def test_remove_guard_cannot_delete_another_project(tmp_path):
    parent = tmp_path / "work"
    parent.mkdir()
    other = tmp_path / "other-project"
    other.mkdir()
    (other / "data").write_text("keep")
    with pytest.raises(ValueError):
        safe_remove_tree(other, parent)
    foreign = parent / "other-project"
    foreign.mkdir()
    with pytest.raises(ValueError):
        safe_remove_tree(foreign, parent)
    assert (other / "data").read_text() == "keep"


def test_completed_wal_requires_exact_size_and_no_symlink(store, tmp_path):
    path = tmp_path / wal_filename(1, 1)
    path.write_bytes(b"incomplete")
    with pytest.raises(ValueError, match="incomplete"):
        store.archive_wal(path)
    path.unlink()
    path.symlink_to(store.root / "cluster.json")
    with pytest.raises(ValueError, match="incomplete"):
        store.archive_wal(path)


def test_base_filename_shape_is_restricted():
    assert BASE_NAME.fullmatch("base-20261118T123456123456Z-aabbccdd")
    assert not BASE_NAME.fullmatch("base-../../other")


def test_atomic_metadata_is_owner_only(store):
    path = store.root / "sample.json"
    atomic_json(path, {"verified": True})
    assert path.stat().st_mode & 0o777 == 0o600
    atomic_json(path, {"verified": False})
    assert json.loads(path.read_text()) == {"verified": False}


@pytest.fixture
def encrypted_store(tmp_path):
    import os
    import shutil
    import subprocess

    binary = os.environ.get("AGE_BINARY") or shutil.which("age")
    if not binary:
        pytest.skip("age is mandatory in the dedicated encryption CI job")
    identity = tmp_path / "identity"
    subprocess.run(
        [str(Path(binary).parent / "age-keygen"), "-o", str(identity)],
        capture_output=True,
        check=True,
    )
    recipient = subprocess.check_output(
        [str(Path(binary).parent / "age-keygen"), "-y", str(identity)],
        text=True,
    ).strip()
    return Store(
        tmp_path / "archive", SYSTEM, binary, [recipient], min_free_bytes=0
    ), identity


def test_real_encrypted_wal_roundtrip_and_crash_retry(
    encrypted_store, tmp_path
):
    from pitr_store import SEGMENT_BYTES

    store, identity = encrypted_store
    original = tmp_path / wal_filename(1, 3)
    with original.open("wb") as out:
        out.write(b"synthetic-private-fixture")
        out.truncate(SEGMENT_BYTES)
    metadata = store.archive_wal(original)
    cipher = store.root / "wal" / metadata["artifact"]
    assert b"synthetic-private-fixture" not in cipher.read_bytes()
    destination = tmp_path / "recovered"
    store.restore_wal(original.name, destination, identity)
    assert digest(destination) == digest(original)
    # A crash after ciphertext publication must not strand the receiver.
    cipher.with_suffix(".json").unlink()
    retry = store.archive_wal(original)
    assert retry["plain_sha256"] == digest(original)
    store.restore_wal(original.name, destination, identity)
    assert digest(destination) == digest(original)


def test_authenticated_cipher_corruption_cannot_publish_wal(
    encrypted_store, tmp_path
):
    from pitr_store import SEGMENT_BYTES

    store, identity = encrypted_store
    original = tmp_path / wal_filename(1, 3)
    with original.open("wb") as out:
        out.truncate(SEGMENT_BYTES)
    metadata = store.archive_wal(original)
    cipher = store.root / "wal" / metadata["artifact"]
    damaged = bytearray(cipher.read_bytes())
    damaged[-1] ^= 1
    cipher.write_bytes(damaged)
    # Recompute the outer checksum to exercise age authentication itself.
    metadata["cipher_sha256"] = digest(cipher)
    atomic_json(cipher.with_suffix(".json"), metadata)
    target = tmp_path / "unpublished"
    with pytest.raises((ValueError, EOFError)):
        store.restore_wal(original.name, target, identity)
    assert not target.exists()
