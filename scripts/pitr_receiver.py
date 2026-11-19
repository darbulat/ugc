"""Receive WAL through a restricted SSH tunnel without restarting PostgreSQL."""

import argparse
import contextlib
import fcntl
import json
import os
import re
import select
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from pitr_store import (
    SEGMENT_BYTES,
    Store,
    atomic_json,
    lsn_number,
    safe_remove_tree,
    utc_now,
)

ROLE = "ugc_pitr_v1"
SLOT = "ugc_pitr_v1"
ROOT = "/var/lib/ugc-pitr/archive"
CORE_SERVICES = ("app", "app_2", "admin", "max_bot", "instagram_webhook")


def checked(command, *, env=None, timeout=30):
    process = subprocess.run(
        command, env=env, capture_output=True, text=True, timeout=timeout
    )
    if process.returncode:
        # Do not log libpq/SSH diagnostics or credentials.
        raise RuntimeError("PITR operation failed: " + Path(command[0]).name)
    return process.stdout.strip()


def load_config(path):
    config = json.loads(Path(path).read_text())
    if config["version"] != 1 or config["root"] != ROOT:
        raise ValueError("Unexpected PITR configuration scope")
    if config["pg_host"] != "127.0.0.1" or config["pg_port"] != 16543:
        raise ValueError("PITR requires its dedicated loopback tunnel")
    if config["ssh_host"] != "31.59.106.143":
        raise ValueError("Unexpected primary host")
    if config["slot"] != SLOT or config["pg_user"] != ROLE:
        raise ValueError("Unexpected replication identity")
    if config["switch_seconds"] < 300 or config["keep_days"] < 7:
        raise ValueError("Unsafe WAL switching or retention interval")
    if config["max_bytes"] > 8 * 1024**3:
        raise ValueError("Archive exceeds its reviewed disk budget")
    if config["min_free_bytes"] < 16 * 1024**3:
        raise ValueError("Insufficient reserve host disk headroom")
    config["config_path"] = str(Path(path).resolve())
    return config


def credentials(name):
    root = os.environ.get("CREDENTIALS_DIRECTORY", "/etc/ugc-pitr/credentials")
    path = Path(root) / name
    if not path.is_file():
        raise ValueError("Required PITR credential is unavailable")
    return path


@contextlib.contextmanager
def private_pgpass(config):
    # systemd credentials may be 0440; libpq rejects any group-readable file.
    # RuntimeDirectory is private tmpfs and systemd removes it on unit stop.
    with tempfile.TemporaryDirectory(
        prefix="auth-", dir=os.environ.get("RUNTIME_DIRECTORY")
    ) as directory:
        with credentials("pgpass").open("rb") as source:
            content = source.read(4097)
        if not 0 < len(content) <= 4096:
            raise ValueError("Invalid replication credential size")
        path = Path(directory) / "pgpass"
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
        yield config | {"private_pgpass": str(path)}


def ssh_command(config):
    return [
        "/usr/bin/ssh",
        "-T",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=yes",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "ExitOnForwardFailure=yes",
        "-o",
        "ConnectTimeout=8",
        "-o",
        "ServerAliveInterval=15",
        "-o",
        "ServerAliveCountMax=3",
        "-o",
        "UserKnownHostsFile=/etc/ugc-pitr/known_hosts",
        "-i",
        str(credentials("tunnel_key")),
    ]


class PostgreSQL:
    def __init__(self, config):
        self.config = config

    def environment(self, *, sql=False):
        env = os.environ.copy()
        for key in ("PGPASSWORD", "PGHOSTADDR", "PGSERVICE", "PGOPTIONS"):
            env.pop(key, None)
        env.update(
            {
                "PGHOST": self.config["pg_host"],
                "PGPORT": str(self.config["pg_port"]),
                "PGUSER": self.config["pg_user"],
                "PGDATABASE": "postgres",
                "PGPASSFILE": self.config.get("private_pgpass")
                or str(credentials("pgpass")),
                "PGCONNECT_TIMEOUT": "5",
                "PGSSLMODE": "disable",
                "PGAPPNAME": SLOT,
            }
        )
        if sql:
            env["PGOPTIONS"] = "-c statement_timeout=5000 -c lock_timeout=1000"
        return env

    def binary(self, name):
        return str(Path(self.config["pg_bin"]) / name)

    def query(self, sql):
        return checked(
            [
                self.binary("psql"),
                "-X",
                "-At",
                "-v",
                "ON_ERROR_STOP=1",
                "--no-password",
                "-c",
                sql,
            ],
            env=self.environment(sql=True),
        )

    def control(self):
        data = json.loads(
            self.query("""
SELECT json_build_object(
 'system_id',(SELECT system_identifier::text FROM pg_control_system()),
 'timeline',(SELECT timeline_id FROM pg_control_checkpoint()),
 'lsn',pg_current_wal_lsn()::text,'now',clock_timestamp(),
 'wal_level',current_setting('wal_level'),
 'segment_bytes',pg_size_bytes(current_setting('wal_segment_size')),
 'synchronous_standby_names',current_setting('synchronous_standby_names'),
 'recovery_parameters',json_build_object(
   'max_connections',current_setting('max_connections'),
   'max_worker_processes',current_setting('max_worker_processes'),
   'max_wal_senders',current_setting('max_wal_senders'),
   'max_prepared_transactions',current_setting('max_prepared_transactions'),
   'max_locks_per_transaction',current_setting('max_locks_per_transaction'),
   'track_commit_timestamp',current_setting('track_commit_timestamp')),
 'in_recovery',pg_is_in_recovery());
""")
        )
        if data["system_id"] != str(self.config["system_id"]):
            raise ValueError("Primary cluster identity changed")
        if data["timeline"] != self.config["timeline"]:
            raise ValueError("A new timeline requires a reviewed new base")
        if data["segment_bytes"] != SEGMENT_BYTES:
            raise ValueError("Unexpected WAL segment size")
        if data["wal_level"] not in ("replica", "logical"):
            raise ValueError("WAL streaming is not enabled")
        if data["in_recovery"] or data["synchronous_standby_names"]:
            raise ValueError("PITR must not become a synchronous dependency")
        return data


def store_from(config):
    return Store(
        config["root"],
        config["system_id"],
        config["age"],
        config["recipients"],
        max_bytes=config["max_bytes"],
        min_free_bytes=config["min_free_bytes"],
    )


def archive_completed(store):
    for path in sorted((store.root / "spool").iterdir()):
        if re.fullmatch(r"[0-9A-F]{24}", path.name):
            store.archive_wal(path)
            path.unlink()
    store.capacity()


def status(store, control, receiver_alive):
    result = {
        "checked_at": utc_now(),
        "system_id": store.system_id,
        "receiver_alive": receiver_alive,
        "base_verified": False,
        "chain_verified": False,
        "primary_lsn": control["lsn"],
    }
    bases = store.metadata("base")
    if bases:
        base = max(bases, key=lambda b: b["finished_at"])
        store.check_artifact(base, "base")
        result["base_verified"] = True
        completed = [
            m
            for m in store.metadata("wal")
            if m["timeline"] == base["timeline"]
        ]
        if completed:
            latest = max(completed, key=lambda m: m["number"])
            covered = (latest["number"] + 1) * SEGMENT_BYTES
            through = f"{covered >> 32:X}/{covered & 0xFFFFFFFF:X}"
            try:
                chain = store.wal_chain(base, through)
            except ValueError:
                result["reason"] = "WAL chain is incomplete"
            else:
                result.update(
                    chain_verified=True,
                    wal_segments=len(chain),
                    base_finished_at=base["finished_at"],
                    recoverable_through_lsn=through,
                    last_completed_wal_at=latest["archived_at"],
                    pending_wal_bytes=max(
                        0, lsn_number(control["lsn"]) - covered
                    ),
                )
    atomic_json(store.root / "status.json", result)
    return result


def stop_child(process):
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def await_primary(pg, tunnel, stopped):
    for _ in range(20):
        if stopped() or tunnel.poll() is not None:
            raise RuntimeError("PITR tunnel did not become ready")
        try:
            return pg.control()
        except RuntimeError:
            time.sleep(1)
    raise RuntimeError("PITR primary preflight deadline exceeded")


def run_receiver(config):
    store, pg = store_from(config), PostgreSQL(config)
    stopped = False

    def terminate(*args):
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGTERM, terminate)
    signal.signal(signal.SIGINT, terminate)
    tunnel = receiver = None
    try:
        tunnel = subprocess.Popen(
            [
                sys.executable,
                "-Es",
                str(Path(__file__).with_name("pitr_tunnel.py")),
                "--config",
                config["config_path"],
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        await_primary(pg, tunnel, lambda: stopped)
        checked(
            [
                pg.binary("pg_receivewal"),
                "--no-password",
                "--create-slot",
                "--if-not-exists",
                "--slot=" + config["slot"],
            ],
            env=pg.environment(),
        )
        receiver = subprocess.Popen(
            [
                pg.binary("pg_receivewal"),
                "--no-password",
                "--synchronous",
                "--slot=" + config["slot"],
                "--directory=" + str(store.root / "spool"),
            ],
            env=pg.environment(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        last_switch, last_maintenance = 0.0, 0.0
        while not stopped:
            if receiver.poll() is not None or tunnel.poll() is not None:
                raise RuntimeError("PITR child exited")
            now = time.monotonic()
            if now - last_maintenance >= 30:
                control = pg.control()
                store.capacity()
                if now - last_switch >= config["switch_seconds"]:
                    pg.query("SELECT pg_switch_wal();")
                    last_switch = now
                archive_completed(store)
                store.prune(config["keep_days"])
                status(store, control, True)
                last_maintenance = now
            time.sleep(1)
    finally:
        stop_child(receiver)
        stop_child(tunnel)
        atomic_json(
            store.root / "status.json",
            {
                "checked_at": utc_now(),
                "receiver_alive": False,
                "chain_verified": False,
                "reason": "receiver stopped",
            },
        )


@contextlib.contextmanager
def primary_backup_gate(config):
    process = subprocess.Popen(
        ssh_command(config)
        + ["deploy@" + config["ssh_host"], "ugc-pitr-backup-lock"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    try:
        readable, _, _ = select.select([process.stdout], [], [], 10)
        if not readable or process.stdout.readline().strip() != b"LOCKED":
            raise RuntimeError("Primary deployment/backup gate is busy")
        yield process
        if process.poll() is not None:
            raise RuntimeError("Primary backup gate expired")
    finally:
        process.stdin.close()
        stop_child(process)
        process.stdout.close()


def memory_headroom(minimum=2 * 1024**3):
    mem = Path("/proc/meminfo").read_text()
    available = int(mem.split("MemAvailable:")[1].split()[0]) * 1024
    if available < minimum:
        raise RuntimeError("Reserve host lacks memory headroom")


def take_base(pg, store):
    recovery_parameters = pg.control()["recovery_parameters"]
    root = store.root / "work"
    with (root / "base.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # A killed oneshot cannot run finally. Only a new holder of the same
        # exclusive base lock may remove its abandoned plaintext staging dirs.
        for abandoned in root.glob("base-work-*"):
            safe_remove_tree(abandoned, root)
        work = Path(tempfile.mkdtemp(prefix="base-work-", dir=root))
        work.rmdir()
        started = utc_now()
        try:
            checked(
                [
                    pg.binary("pg_basebackup"),
                    "--no-password",
                    "--pgdata=" + str(work),
                    "--format=plain",
                    "--wal-method=stream",
                    "--checkpoint=spread",
                    "--max-rate=5M",
                    "--manifest-checksums=SHA256",
                    "--label=ugc-pitr-v1",
                ],
                env=pg.environment(),
                timeout=900,
            )
            checked([pg.binary("pg_verifybackup"), str(work)], timeout=300)
            return store.archive_base(
                work,
                started_at=started,
                finished_at=utc_now(),
                recovery_parameters=recovery_parameters,
            )
        finally:
            if work.exists():
                safe_remove_tree(work, root)


def create_base(config):
    store, pg = store_from(config), PostgreSQL(config)
    memory_headroom()
    store.capacity(1024**3)
    with primary_backup_gate(config):
        pg.control()
        metadata = take_base(pg, store)
        print(
            json.dumps(
                {"base_verified": True, "artifact": metadata["artifact"]}
            ),
            flush=True,
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("receive", "base", "status"))
    parser.add_argument("--config", required=True, type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    config = load_config(args.config)
    if args.action == "status":
        print(
            json.dumps(
                json.loads((Path(config["root"]) / "status.json").read_text())
            )
        )
        return
    with private_pgpass(config) as authenticated:
        if args.action == "receive":
            run_receiver(authenticated)
        else:
            create_base(authenticated)


if __name__ == "__main__":
    main()
