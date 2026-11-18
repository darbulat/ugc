"""Provision one bounded PITR reader; never restart or recreate production."""

import argparse
import base64
import fcntl
import json
import os
import re
import secrets
import select
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import production_release as release

ROLE = "ugc_pitr_v1"
STATE = Path("/opt/myapp/ugc-ops/pitr-primary-v1")
REMOTE_IP = "194.87.131.138"
HBA_LINES = (
    f"host replication {ROLE} 172.18.0.1/32 scram-sha-256",
    f"host postgres {ROLE} 172.18.0.1/32 scram-sha-256",
    f"host replication {ROLE} 0.0.0.0/0 reject",
    f"host all {ROLE} 0.0.0.0/0 reject",
    f"host replication {ROLE} ::/0 reject",
    f"host all {ROLE} ::/0 reject",
)


def sql_quote(value):
    return "'" + value.replace("'", "''") + "'"


def query(sql):
    return release.checked(
        [
            "docker",
            "exec",
            "-i",
            "ugc-db-1",
            "sh",
            "-c",
            "exec psql -X -At -v ON_ERROR_STOP=1 "
            '-U "$POSTGRES_USER" -d postgres',
        ],
        stdin=sql,
        timeout=20,
    ).strip()


def audit():
    return json.loads(
        query("""
SELECT json_build_object(
 'system_id',(SELECT system_identifier::text FROM pg_control_system()),
 'timeline',(SELECT timeline_id FROM pg_control_checkpoint()),
 'version',current_setting('server_version_num'),
 'wal_level',current_setting('wal_level'),
 'archive_mode',current_setting('archive_mode'),
 'max_wal_senders',current_setting('max_wal_senders')::int,
 'max_replication_slots',current_setting('max_replication_slots')::int,
 'slot_limit',current_setting('max_slot_wal_keep_size'),
 'synchronous_standby_names',current_setting('synchronous_standby_names'),
 'full_page_writes',current_setting('full_page_writes'),
 'fsync',current_setting('fsync'),
 'pending_restart',(SELECT count(*) FROM pg_settings WHERE pending_restart),
 'senders',(SELECT count(*) FROM pg_stat_replication),
 'slots',(SELECT count(*) FROM pg_replication_slots),
 'basebackups',(SELECT count(*) FROM pg_stat_progress_basebackup),
 'database_bytes',(SELECT sum(pg_database_size(oid)) FROM pg_database),
 'extra_tablespaces',(SELECT count(*) FROM pg_tablespace
                      WHERE spcname NOT IN ('pg_default','pg_global')),
 'hba_errors',(SELECT count(*) FROM pg_hba_file_rules WHERE error IS NOT NULL),
 'role_exists',EXISTS(SELECT FROM pg_roles WHERE rolname='ugc_pitr_v1'));
""")
    )


def validate_preflight(data, expected_system_id):
    if data["system_id"] != expected_system_id:
        raise ValueError("Unexpected production PostgreSQL cluster")
    if not 160000 <= int(data["version"]) < 170000:
        raise ValueError("This rollout is reviewed for PostgreSQL 16")
    if data["wal_level"] not in ("replica", "logical"):
        raise ValueError("WAL level requires a separately approved restart")
    if data["archive_mode"] != "off" or data["synchronous_standby_names"]:
        raise ValueError("Unexpected archive/synchronous replication settings")
    if data["full_page_writes"] != "on" or data["fsync"] != "on":
        raise ValueError("PostgreSQL durability preconditions not met")
    if data["pending_restart"] or data["hba_errors"]:
        raise ValueError("Resolve pending PostgreSQL configuration first")
    if (
        data["max_wal_senders"] - data["senders"] < 3
        or data["max_replication_slots"] - data["slots"] < 2
    ):
        raise ValueError("Insufficient spare replication capacity")
    if data["extra_tablespaces"] or data["database_bytes"] > 1024**3:
        raise ValueError("Reassess archive sizing/tablespaces before rollout")


def container_state():
    names = [
        "ugc-" + name + "-1"
        for name in (
            "db",
            "app",
            "app_2",
            "admin",
            "max_bot",
            "instagram_webhook",
        )
    ]
    values = json.loads(release.checked(["docker", "inspect", *names]))
    for item in values:
        state = item["State"]
        if (
            state["Status"] != "running"
            or state.get("OOMKilled")
            or state.get("Health", {}).get("Status") != "healthy"
        ):
            raise RuntimeError("Core services must be healthy before PITR")
    return {
        x["Name"]: (x["Id"], x["State"]["StartedAt"], x["RestartCount"])
        for x in values
    }


def verify_transport():
    state = release.inspect("ugc-db-1")
    bindings = state["NetworkSettings"]["Ports"].get("5432/tcp") or []
    gateways = {
        network.get("Gateway")
        for network in state["NetworkSettings"]["Networks"].values()
    }
    if not any(b["HostPort"] == "65432" for b in bindings):
        raise ValueError("Primary database port mapping changed")
    if gateways != {"172.18.0.1"}:
        raise ValueError(
            "Re-audit Docker gateway before adding exact HBA grants"
        )


def read_hba():
    return release.checked(
        [
            "docker",
            "exec",
            "ugc-db-1",
            "sh",
            "-c",
            'cat "$PGDATA/pg_hba.conf"',
        ]
    )


def write_hba(content):
    release.checked(
        [
            "docker",
            "exec",
            "-i",
            "ugc-db-1",
            "sh",
            "-c",
            'set -e; p=$(mktemp "$PGDATA/pg_hba.conf.pitr.XXXXXX"); '
            'cat > "$p"; chown postgres:postgres "$p"; chmod 600 "$p"; '
            'mv "$p" "$PGDATA/pg_hba.conf"',
        ],
        stdin=content,
    )


def authorized_entry(public):
    if not re.fullmatch(r"ssh-ed25519 [A-Za-z0-9+/=]+(?: [^\n]*)?", public):
        raise ValueError("Expected one public Ed25519 tunnel key")
    command = "/usr/bin/python3 -Es /opt/myapp/ugc-ops/pitr_primary.py ssh"
    return f'restrict,from="{REMOTE_IP}",command="{command}" {public.strip()}'


def atomic_text(path, content):
    import tempfile

    path = Path(path)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    fd, temporary = tempfile.mkstemp(prefix=".pitr-new-", dir=path.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w") as out:
            out.write(content)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
        release.sync_directory(path.parent)
    finally:
        Path(temporary).unlink(missing_ok=True)


def encrypted_bootstrap(payload, data, password):
    recipients = payload["bootstrap_recipients"]
    if len(recipients) != 2 or any(
        not re.fullmatch(r"age1[0-9a-z]{58}", r) for r in recipients
    ):
        raise ValueError("Two public bootstrap recipients are required")
    env = release.environment_of(release.inspect("ugc-db-1"))
    bootstrap = json.dumps(
        {
            "pgpass": f"127.0.0.1:16543:*:{ROLE}:{password}\n",
            "system_id": data["system_id"],
            "timeline": data["timeline"],
            "application_database": env["POSTGRES_DB"],
            "restore_superuser": env["POSTGRES_USER"],
        }
    )
    command = ["/opt/myapp/ugc-ops/bin/age", "--encrypt"]
    for recipient in recipients:
        command += ["--recipient", recipient]
    result = subprocess.run(
        command, input=bootstrap.encode(), capture_output=True, timeout=20
    )
    if result.returncode:
        raise RuntimeError("PITR bootstrap encryption failed")
    return result.stdout


class Provision:
    def __init__(self, payload):
        self.payload = payload
        self.data = audit()
        validate_preflight(self.data, str(payload["system_id"]))
        if STATE.exists() or self.data["role_exists"]:
            raise ValueError("Existing PITR installation requires review")
        self.before = container_state()
        verify_transport()
        self.public = payload["tunnel_public_key"].strip()
        self.entry = authorized_entry(self.public)
        self.keys = Path.home() / ".ssh/authorized_keys"
        self.original_keys = self.keys.read_text()
        if self.public.split()[1] in self.original_keys:
            raise ValueError("Tunnel key already has an unrelated grant")
        if self.keys.is_symlink() or self.keys.stat().st_mode & 0o022:
            raise ValueError("Unsafe existing SSH authorization file")
        self.hba = read_hba()
        if any(ROLE in line for line in self.hba.splitlines()):
            raise ValueError("Existing HBA role must not be overwritten")
        self.candidate_hba = (
            "# ugc-pitr-v1: isolated backup role\n"
            + "\n".join(HBA_LINES)
            + "\n"
            + self.hba
        )
        self.role_created = self.retention_changed = False
        self.hba_changed = self.keys_changed = False

    def apply(self, password):
        # Suppress statement/error text only for this administrative connection.
        query(
            "SET log_statement='none'; SET log_min_duration_statement=-1; "
            "SET log_min_error_statement='panic';\n"
            f"CREATE ROLE {ROLE} LOGIN REPLICATION NOSUPERUSER "
            "NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS "
            f"CONNECTION LIMIT 4 PASSWORD {sql_quote(password)};"
        )
        self.role_created = True
        query(
            f"GRANT CONNECT ON DATABASE postgres TO {ROLE};\n"
            "GRANT EXECUTE ON FUNCTION pg_control_system(), "
            f"pg_control_checkpoint(), pg_switch_wal() TO {ROLE};"
        )
        query("ALTER SYSTEM SET max_slot_wal_keep_size='2GB';")
        self.retention_changed = True
        if read_hba() != self.hba:
            raise RuntimeError("Concurrent HBA update detected")
        self.hba_changed = True
        write_hba(self.candidate_hba)
        query("SELECT pg_reload_conf();")
        errors = query(
            "SELECT count(*) FROM pg_hba_file_rules WHERE error IS NOT NULL;"
        )
        if errors != "0" or read_hba() != self.candidate_hba:
            raise RuntimeError("PITR HBA validation failed")
        if self.keys.read_text() != self.original_keys:
            raise RuntimeError("Concurrent SSH authorization change")
        separator = "" if self.original_keys.endswith("\n") else "\n"
        atomic_text(
            self.keys, self.original_keys + separator + self.entry + "\n"
        )
        self.keys_changed = True
        if container_state() != self.before:
            raise RuntimeError("Production containers changed during setup")
        current = audit()
        if current["slot_limit"] != "2GB" or current["pending_restart"]:
            raise RuntimeError("WAL retention reload verification failed")

    def rollback(self):
        if self.keys_changed:
            current = self.keys.read_text()
            lines = current.splitlines(keepends=True)
            atomic_text(
                self.keys,
                "".join(line for line in lines if line.strip() != self.entry),
            )
        if self.hba_changed:
            current = read_hba()
            prefix = self.candidate_hba.removesuffix(self.hba)
            if not current.startswith(prefix):
                raise RuntimeError("Concurrent HBA edit requires manual review")
            write_hba(current.removeprefix(prefix))
        if self.retention_changed:
            query(
                "ALTER SYSTEM SET max_slot_wal_keep_size="
                + sql_quote(self.data["slot_limit"])
                + ";"
            )
        query("SELECT pg_reload_conf();")
        if self.role_created:
            query(f"DROP OWNED BY {ROLE}; DROP ROLE {ROLE};")


def provision(payload):
    setup = Provision(payload)
    password = secrets.token_urlsafe(48)
    cipher = encrypted_bootstrap(payload, setup.data, password)
    STATE.mkdir(mode=0o700)
    release.private_json(
        STATE / "previous.json",
        {
            "slot_limit": setup.data["slot_limit"],
            "system_id": setup.data["system_id"],
            "containers": setup.before,
            "hba": setup.hba,
        },
    )
    try:
        setup.apply(password)
        release.private_json(
            STATE / "installed.json",
            {
                "system_id": setup.data["system_id"],
                "timeline": setup.data["timeline"],
                "role": ROLE,
                "slot_limit": "2GB",
                "tunnel_public_key": setup.public,
                "installed_at": time.time(),
                "containers_unchanged": True,
            },
        )
        fd = os.open(
            STATE / "bootstrap.age", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
        )
        with os.fdopen(fd, "wb") as out:
            out.write(cipher)
            out.flush()
            os.fsync(out.fileno())
    except BaseException:
        setup.rollback()
        raise
    print(
        json.dumps(
            {
                "system_id": setup.data["system_id"],
                "timeline": setup.data["timeline"],
                "bootstrap_base64": base64.b64encode(cipher).decode(),
                "containers_unchanged": True,
            }
        ),
        flush=True,
    )


def relay_database():
    # The forced command exposes only this database endpoint over SSH stdio;
    # authorized_keys keeps all OpenSSH forwarding and shell access disabled.
    with socket.create_connection(("127.0.0.1", 65432), timeout=8) as stream:
        stream.settimeout(None)

        def receive():
            try:
                while data := stream.recv(64 * 1024):
                    pending = memoryview(data)
                    while pending:
                        pending = pending[os.write(1, pending) :]
            finally:
                os._exit(0)

        threading.Thread(target=receive, daemon=True).start()
        while data := os.read(0, 64 * 1024):
            stream.sendall(data)
        stream.shutdown(socket.SHUT_WR)
        threading.Event().wait(30)


def ssh_gate():
    if os.environ.get("SSH_ORIGINAL_COMMAND") != "ugc-pitr-backup-lock":
        raise ValueError("Only the backup deployment gate is allowed")
    with release.open_lock("/tmp/ugc-production-deploy.lock") as lock:
        fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
        with release.open_lock("/tmp/ugc-pitr-base.lock") as base_lock:
            fcntl.flock(base_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            before = container_state()
            data = audit()
            if data["basebackups"] or data["database_bytes"] > 1024**3:
                raise ValueError("Another base backup or sizing review pending")
            free = os.statvfs("/opt/myapp")
            if free.f_bavail * free.f_frsize < 16 * 1024**3:
                raise ValueError("Primary disk headroom too low")
            print("LOCKED", flush=True)
            # The caller holds stdin open; no commands or payload are read.
            select.select([sys.stdin], [], [], 1800)
            if container_state() != before:
                raise RuntimeError("Production changed during backup gate")


def probe(action, token):
    if not re.fullmatch(r"[0-9a-f]{16}", token):
        raise ValueError("Invalid recovery probe token")
    names = [
        "ugc_pitr_probe_" + token + "_" + phase for phase in ("before", "after")
    ]
    if action == "probe":
        for name in names:
            exists = query(
                "SELECT count(*) FROM pg_roles WHERE rolname="
                + sql_quote(name)
                + ";"
            )
            if exists != "0":
                raise ValueError("Probe role already exists")
        query(f"CREATE ROLE {names[0]} NOLOGIN NOSUPERUSER NOCREATEROLE;")
        target = query("SELECT clock_timestamp();")
        time.sleep(1)
        query(f"CREATE ROLE {names[1]} NOLOGIN NOSUPERUSER NOCREATEROLE;")
        through = query("SELECT pg_current_wal_lsn();")
        query("SELECT pg_switch_wal();")
        print(
            json.dumps(
                {
                    "before_role": names[0],
                    "after_role": names[1],
                    "target_time": target,
                    "through_lsn": through,
                }
            )
        )
    else:
        for name in names:
            login = query(
                "SELECT rolcanlogin FROM pg_roles WHERE rolname="
                + sql_quote(name)
                + ";"
            )
            if login not in ("", "f"):
                raise ValueError("Refusing to drop a login-capable role")
            query(f"DROP ROLE IF EXISTS {name};")
        print(json.dumps({"probe_roles_removed": True}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=("audit", "provision", "ssh", "probe", "cleanup-probe"),
    )
    parser.add_argument("--token")
    args = parser.parse_args()
    os.umask(0o077)
    if args.action == "ssh":
        if os.environ.get("SSH_ORIGINAL_COMMAND") == "ugc-pitr-db":
            relay_database()
        else:
            ssh_gate()
        return
    with release.open_lock("/tmp/ugc-production-deploy.lock") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action == "audit":
            print(json.dumps(audit()))
        elif args.action == "provision":
            provision(json.load(sys.stdin))
        else:
            probe(args.action, args.token or "")


if __name__ == "__main__":
    main()
