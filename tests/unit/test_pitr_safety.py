"""Regression checks for production and reserve isolation boundaries."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import pitr_operator as operator  # noqa: E402
import pitr_primary as primary  # noqa: E402
from pitr_receiver import load_config  # noqa: E402


def preflight():
    return {
        "system_id": "7598122211340197923",
        "version": "160004",
        "wal_level": "logical",
        "archive_mode": "off",
        "synchronous_standby_names": "",
        "full_page_writes": "on",
        "fsync": "on",
        "pending_restart": 0,
        "hba_errors": 0,
        "max_wal_senders": 4,
        "senders": 0,
        "max_replication_slots": 4,
        "slots": 0,
        "extra_tablespaces": 0,
        "database_bytes": 350 * 1024**2,
    }


@pytest.mark.parametrize(
    "key,value",
    [
        ("system_id", "111111111111"),
        ("version", "170001"),
        ("wal_level", "minimal"),
        ("archive_mode", "on"),
        ("synchronous_standby_names", "*"),
        ("fsync", "off"),
        ("full_page_writes", "off"),
        ("pending_restart", 1),
        ("hba_errors", 1),
        ("senders", 2),
        ("slots", 3),
        ("extra_tablespaces", 1),
        ("database_bytes", 2 * 1024**3),
    ],
)
def test_primary_rejects_unsafe_or_changed_preconditions(key, value):
    data = preflight()
    primary.validate_preflight(data, data["system_id"])
    data[key] = value
    with pytest.raises(ValueError):
        primary.validate_preflight(data, "7598122211340197923")


def test_tunnel_key_only_gets_one_forward_and_forced_gate():
    grant = primary.authorized_entry("ssh-ed25519 AAAAFIXTURE reserve")
    assert grant.startswith('restrict,from="194.87.131.138",')
    assert "port-forwarding" not in grant
    assert (
        'command="/usr/bin/python3 -Es /opt/myapp/ugc-ops/pitr_primary.py ssh"'
        in grant
    )
    with pytest.raises(ValueError):
        primary.authorized_entry("ssh-ed25519 AAAA\nssh-ed25519 OTHER")


def test_forced_gate_cannot_execute_an_arbitrary_command(monkeypatch):
    monkeypatch.setenv("SSH_ORIGINAL_COMMAND", "rm -rf /")
    with pytest.raises(ValueError, match="Only the backup"):
        primary.ssh_gate()


def test_reserve_operator_rejects_existing_project_unit(monkeypatch):
    def forbid(*args, **kwargs):
        pytest.fail("No external command should run for a foreign unit")

    monkeypatch.setattr(operator, "run", forbid)
    with pytest.raises(ValueError, match="owned PITR"):
        operator.systemctl("stop", "reels-editing-worker.service")
    with pytest.raises(ValueError, match="owned PITR"):
        operator.systemctl("restart", "ugc-pitr-receiver.service")


def test_reserve_forced_command_rejects_shell(monkeypatch):
    monkeypatch.setattr(operator.os, "geteuid", lambda: 0)
    monkeypatch.setattr(sys, "argv", ["pitr_operator.py"])
    monkeypatch.setenv("SSH_ORIGINAL_COMMAND", "sh -c id")
    with pytest.raises(ValueError, match="restricted PITR"):
        operator.main()


def test_receiver_configuration_cannot_target_other_projects(tmp_path):
    config = {
        "version": 1,
        "root": "/var/lib/ugc-pitr/archive",
        "pg_host": "127.0.0.1",
        "pg_port": 16543,
        "ssh_host": "31.59.106.143",
        "slot": "ugc_pitr_v1",
        "pg_user": "ugc_pitr_v1",
        "switch_seconds": 300,
        "keep_days": 7,
        "max_bytes": 8 * 1024**3,
        "min_free_bytes": 16 * 1024**3,
    }
    path = tmp_path / "config.json"
    path.write_text(json.dumps(config))
    assert load_config(path) == config | {"config_path": str(path)}
    for key, value in [
        ("root", "/var/lib/postgresql"),
        ("pg_port", 5432),
        ("pg_host", "0.0.0.0"),
        ("pg_user", "postgres"),
        ("max_bytes", 100 * 1024**3),
        ("keep_days", 1),
    ]:
        path.write_text(json.dumps(config | {key: value}))
        with pytest.raises(ValueError):
            load_config(path)


def test_shared_receiver_budget_and_isolated_restore_contract():
    directory = Path(__file__).resolve().parents[2] / "config/pitr"
    budget = (directory / "ugc-pitr.slice").read_text()
    assert "MemoryMax=256M\n" in budget
    assert "MemorySwapMax=0\n" in budget
    for unit in ("receiver", "base"):
        text = (directory / f"ugc-pitr-{unit}.service").read_text()
        assert "Slice=ugc-pitr.slice\n" in text
        assert "User=ugc-pitr\n" in text
    text = (directory / "ugc-pitr-restore.service").read_text()
    assert "MemoryMax=768M\n" in text
    assert "PrivateNetwork=yes\n" in text
    assert "RestrictAddressFamilies=AF_UNIX\n" in text
    assert "RootDirectory=/opt/ugc-pitr/runtime\n" in text
    assert "ReadWritePaths=/restore\n" in text
    assert "Restart=" not in text


def test_pg_relay_transports_binary_without_opening_ssh_forwarding(monkeypatch):
    import socket
    import threading
    from types import SimpleNamespace

    import pitr_tunnel

    command = [
        sys.executable,
        "-c",
        "import sys; data=sys.stdin.buffer.read(); "
        "sys.stdout.buffer.write(data[::-1])",
    ]
    monkeypatch.setattr(pitr_tunnel, "ssh_command", lambda config: command)
    client, backend = socket.socketpair()
    server = SimpleNamespace(
        config={"ssh_host": "fixture"},
        capacity=threading.BoundedSemaphore(4),
        lock=threading.Lock(),
        children=set(),
    )
    thread = threading.Thread(
        target=pitr_tunnel.Connection, args=(backend, None, server)
    )
    thread.start()
    try:
        client.settimeout(5)
        packet = b"\x00\x00\x00\x08\x04\xd2\x16\x2f"
        client.sendall(packet)
        client.shutdown(socket.SHUT_WR)
        assert client.recv(1024) == packet[::-1]
        thread.join(timeout=5)
        assert not thread.is_alive()
        assert not server.children
    finally:
        client.close()
        backend.close()


def test_rollback_removes_only_its_ssh_and_hba_grants(monkeypatch, tmp_path):
    setup = object.__new__(primary.Provision)
    setup.keys = tmp_path / "authorized_keys"
    setup.entry = 'restrict,command="pitr" ssh-ed25519 OWN'
    original = "ssh-ed25519 BEFORE\n"
    concurrent = "ssh-ed25519 OTHER-CHAT\n"
    setup.keys.write_text(original + setup.entry + "\n" + concurrent)
    setup.hba = "original rule\n"
    setup.candidate_hba = "owned prefix\n" + setup.hba
    hba = {"value": setup.candidate_hba + "other chat rule\n"}
    monkeypatch.setattr(primary, "read_hba", lambda: hba["value"])
    monkeypatch.setattr(
        primary, "write_hba", lambda text: hba.update(value=text)
    )
    monkeypatch.setattr(primary, "query", lambda sql: "")
    setup.keys_changed = setup.hba_changed = True
    setup.retention_changed = setup.role_created = False
    setup.rollback()
    assert setup.keys.read_text() == original + concurrent
    assert hba["value"] == setup.hba + "other chat rule\n"


def test_recovery_keeps_primary_minimums_instead_of_lowering_connections():
    from pitr_restore_isolated import recovery_settings

    settings = {
        "max_connections": "300",
        "max_worker_processes": "8",
        "max_wal_senders": "4",
        "max_prepared_transactions": "0",
        "max_locks_per_transaction": "64",
        "track_commit_timestamp": "off",
    }
    assert "max_connections = '300'" in recovery_settings(settings)
    with pytest.raises(ValueError, match="Missing"):
        recovery_settings({"max_connections": "10"})
    with pytest.raises(ValueError, match="Invalid"):
        recovery_settings(settings | {"max_connections": "100';include='bad"})
