"""Synthetic database only; executed inside an isolated Docker fixture."""

import json
import os
import secrets
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, "/pitr")
import pitr_primary  # noqa: E402
import pitr_tunnel  # noqa: E402
from pitr_receiver import (  # noqa: E402
    PostgreSQL,
    archive_completed,
    private_pgpass,
    take_base,
)
from pitr_restore_isolated import prepare, verify  # noqa: E402
from pitr_store import Store  # noqa: E402

ROOT = Path("/work")
AGE = "/tools/age"
BIN = "/usr/lib/postgresql/16/bin"


def admin(sql, database="fixture"):
    env = os.environ | {
        "PGHOST": "127.0.0.1",
        "PGPORT": "5432",
        "PGUSER": "postgres",
        "PGDATABASE": database,
        "PGPASSWORD": "fixture",
    }
    result = subprocess.run(
        [BIN + "/psql", "-X", "-At", "-v", "ON_ERROR_STOP=1", "-c", sql],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode:
        raise RuntimeError("Synthetic SQL failed: " + result.stderr)
    return result.stdout.strip()


def setup():
    native_query = pitr_primary.query
    pitr_primary.query = admin
    try:
        audited = pitr_primary.audit()
    finally:
        pitr_primary.query = native_query
    assert audited["pending_restart"] == 1
    assert audited["max_replication_slots"] == 4
    pitr_primary.validate_preflight(audited, audited["system_id"])
    postmaster_started = admin("SELECT pg_postmaster_start_time();")
    keys = ROOT / "keys"
    keys.mkdir(mode=0o700)
    subprocess.run(
        ["/tools/age-keygen", "-o", str(keys / "identity")],
        check=True,
        capture_output=True,
    )
    recipient = subprocess.check_output(
        ["/tools/age-keygen", "-y", str(keys / "identity")], text=True
    ).strip()
    creds = ROOT / "credentials"
    creds.mkdir(mode=0o700)
    password_file = creds / "pgpass"
    password_file.write_text("127.0.0.1:16543:*:ugc_pitr_v1:fixture-replica\n")
    password_file.chmod(0o440)
    os.environ["CREDENTIALS_DIRECTORY"] = str(creds)
    admin(
        "CREATE ROLE ugc_pitr_v1 LOGIN REPLICATION NOSUPERUSER "
        "NOCREATEDB NOCREATEROLE NOINHERIT CONNECTION LIMIT 4 "
        "PASSWORD 'fixture-replica'; "
        "CREATE TABLE fixture_proof(id integer primary key, value text); "
        "INSERT INTO fixture_proof VALUES(1,'initial');"
    )
    admin(
        "GRANT EXECUTE ON FUNCTION pg_control_system(), "
        "pg_control_checkpoint(), pg_switch_wal() TO ugc_pitr_v1;",
        database="postgres",
    )
    system_id = admin("SELECT system_identifier::text FROM pg_control_system()")
    config = {
        "root": str(ROOT / "archive"),
        "system_id": system_id,
        "timeline": 1,
        "age": AGE,
        "recipients": [recipient],
        "max_bytes": 2 * 1024**3,
        "min_free_bytes": 0,
        "pg_host": "127.0.0.1",
        "pg_port": 16543,
        "ssh_host": "synthetic",
        "pg_user": "ugc_pitr_v1",
        "pg_bin": BIN,
        "restore_superuser": "postgres",
        "application_database": "fixture",
    }
    with private_pgpass(config) as authenticated:
        private_path = Path(authenticated["private_pgpass"])
        assert private_path.stat().st_mode & 0o777 == 0o600
        stream_and_prepare(config, authenticated, keys, postmaster_started)
    assert not private_path.exists()
    assert password_file.stat().st_mode & 0o777 == 0o440
    print(
        json.dumps(
            {
                "systemd_credential_supported": True,
                "private_pgpass_removed": True,
            }
        )
    )


def stream_and_prepare(config, authenticated, keys, postmaster_started):
    store = Store(
        config["root"],
        config["system_id"],
        AGE,
        config["recipients"],
        max_bytes=2 * 1024**3,
        min_free_bytes=0,
    )
    # Exercise both production byte-relay implementations. The fixture replaces
    # only the SSH transport with a local child process; no public host is used.
    relay_code = (
        "import sys;sys.path.insert(0,'/pitr');import pitr_primary;"
        "connect=pitr_primary.socket.create_connection;"
        "pitr_primary.socket.create_connection=lambda *a,**k:"
        "connect(('127.0.0.1',5432),timeout=8);"
        "pitr_primary.relay_database()"
    )
    pitr_tunnel.ssh_command = lambda config: [sys.executable, "-c", relay_code]
    relay = pitr_tunnel.Relay(config)
    threading.Thread(target=relay.serve_forever, daemon=True).start()
    pg = PostgreSQL(authenticated)
    pg.control()
    subprocess.run(
        [
            BIN + "/pg_receivewal",
            "--create-slot",
            "--slot=ugc_pitr_v1",
            "--no-password",
        ],
        env=pg.environment(),
        capture_output=True,
        check=True,
    )
    receiver = subprocess.Popen(
        [
            BIN + "/pg_receivewal",
            "--synchronous",
            "--slot=ugc_pitr_v1",
            "--directory=" + str(store.root / "spool"),
            "--no-password",
        ],
        env=pg.environment(),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        base = take_base(pg, store)
        token = secrets.token_hex(8)
        before, after = (
            "ugc_pitr_probe_" + token + "_" + suffix
            for suffix in ("before", "after")
        )
        admin(
            f"CREATE ROLE {before} NOLOGIN; "
            "INSERT INTO fixture_proof VALUES(2,'keep-before-delete');"
        )
        target = admin("SELECT clock_timestamp();")
        time.sleep(0.2)
        admin(
            f"CREATE ROLE {after} NOLOGIN; "
            "DELETE FROM fixture_proof WHERE id=2;"
        )
        through = admin("SELECT pg_current_wal_lsn();")
        pg.query("SELECT pg_switch_wal();")
        probe = {
            "before_role": before,
            "after_role": after,
            "target_time": target,
            "through_lsn": through,
        }
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            archive_completed(store)
            try:
                chain = store.wal_chain(base, through)
            except ValueError:
                time.sleep(0.2)
            else:
                break
        else:
            raise RuntimeError("Synthetic WAL chain did not complete")
        assert admin("SELECT count(*) FROM fixture_proof WHERE id=2") == "0"
        required = store.root / "wal" / chain[-1]["artifact"]
        hidden = required.with_suffix(".hidden")
        required.rename(hidden)
        try:
            store.wal_chain(base, through)
        except (ValueError, FileNotFoundError):
            pass
        else:
            raise AssertionError("Missing WAL was accepted")
        hidden.rename(required)
        restore_root = ROOT / "restore"
        restore_root.mkdir(mode=0o700)
        directory = prepare(config, probe, keys / "identity", root=restore_root)
        # Unix sockets need a Linux volume, not a macOS Docker bind mount.
        (directory / "socket").rmdir()
        (directory / "socket").symlink_to("/socket")
        (ROOT / "prepared-name").write_text(directory.name)
        (ROOT / "config.json").write_text(json.dumps(config))
        assert admin("SELECT pg_postmaster_start_time();") == postmaster_started
        print(
            json.dumps(
                {
                    "base_encrypted": True,
                    "wal_segments": len(chain),
                    "missing_wal_rejected": True,
                    "production_byte_relays_exercised": True,
                    "command_line_slot_override_accepted": True,
                    "database_restarted": False,
                    "prepared": directory.name,
                }
            )
        )
    finally:
        receiver.terminate()
        receiver.wait(timeout=10)
        relay.shutdown()
        relay.close_children()
        relay.server_close()


def proof():
    config = json.loads((ROOT / "config.json").read_text())
    directory = ROOT / "restore" / (ROOT / "prepared-name").read_text()
    result = verify(config, directory)
    env = os.environ | {
        "PGHOST": str(directory / "socket"),
        "PGPORT": "16544",
        "PGUSER": "postgres",
        "PGDATABASE": "fixture",
    }
    value = subprocess.check_output(
        [
            BIN + "/psql",
            "-X",
            "-At",
            "-c",
            "SELECT value FROM fixture_proof WHERE id=2;",
        ],
        env=env,
        text=True,
    ).strip()
    assert value == "keep-before-delete"
    assert not (directory / "pgdata/standby.signal").exists()
    print(
        json.dumps(
            result
            | {
                "deleted_row_recovered": True,
                "target_paused_without_promotion": True,
            }
        )
    )


if __name__ == "__main__":
    os.umask(0o077)
    {"setup": setup, "proof": proof}[sys.argv[1]]()
