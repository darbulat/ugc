"""Prepare a new isolated recovery directory; never access live PGDATA."""

import argparse
import json
import os
import re
import tempfile
from pathlib import Path

from pitr_receiver import checked, load_config, memory_headroom, store_from
from pitr_store import atomic_json, timestamp

RESTORE_ROOT = Path("/var/lib/ugc-pitr-restore")
RECOVERY_PARAMETERS = {
    "max_connections",
    "max_worker_processes",
    "max_wal_senders",
    "max_prepared_transactions",
    "max_locks_per_transaction",
    "track_commit_timestamp",
}


def recovery_settings(parameters):
    if set(parameters) != RECOVERY_PARAMETERS:
        raise ValueError("Missing required primary recovery parameters")
    result = []
    for name, value in sorted(parameters.items()):
        valid = (
            value in ("on", "off")
            if name == "track_commit_timestamp"
            else bool(re.fullmatch(r"[0-9]{1,6}", str(value)))
        )
        if not valid:
            raise ValueError("Invalid primary recovery parameter")
        result.append(f"{name} = '{value}'")
    return result


def validate_probe(probe):
    first = re.fullmatch(
        r"ugc_pitr_probe_([0-9a-f]{16})_before", probe["before_role"]
    )
    if not first or probe["after_role"] != (
        "ugc_pitr_probe_" + first[1] + "_after"
    ):
        raise ValueError("Invalid isolated recovery probe")
    timestamp(probe["target_time"])


def prepare(config, probe, identity, *, root=RESTORE_ROOT):
    validate_probe(probe)
    root = Path(root)
    if root.is_symlink() or root.stat().st_mode & 0o022:
        raise ValueError("Recovery root is not private")
    store = store_from(config)
    base = store.select_base(probe["target_time"])
    chain = store.wal_chain(base, probe["through_lsn"])
    directory = Path(tempfile.mkdtemp(prefix="restore-work-", dir=root))
    data = directory / "pgdata"
    store.restore_base(base, data, identity)
    checked(
        [str(Path(config["pg_bin"]) / "pg_verifybackup"), str(data)],
        timeout=300,
    )
    (directory / "socket").mkdir(mode=0o700)
    (directory / "hba.conf").write_text("local all all trust\n")
    # Paths here are inside the private RootDirectory, not host PostgreSQL.
    lines = [
        "restore_command = '/tools/fetch-wal %f %p'",
        "recovery_target_time = '"
        + probe["target_time"].replace("'", "''")
        + "'",
        "recovery_target_action = 'pause'",
        "recovery_target_timeline = '" + str(base["timeline"]) + "'",
        "primary_conninfo = ''",
        "archive_mode = 'off'",
        "synchronous_standby_names = ''",
    ] + recovery_settings(base["recovery_parameters"])
    (data / "postgresql.auto.conf").write_text("\n".join(lines) + "\n")
    (data / "standby.signal").unlink(missing_ok=True)
    (data / "recovery.signal").touch(mode=0o600)
    (data / "postmaster.pid").unlink(missing_ok=True)
    checksums = [m["cipher_sha256"] + " " + m["artifact"] for m in chain]
    (directory / "wal-checksums").write_text("\n".join(checksums) + "\n")
    atomic_json(
        directory / "probe.json",
        probe
        | {
            "base_artifact": base["artifact"],
            "system_id": config["system_id"],
            "timeline": base["timeline"],
            "wal_segments": len(chain),
        },
    )
    return directory


def verify(config, directory):
    directory = Path(directory)
    probe = json.loads((directory / "probe.json").read_text())
    validate_probe(probe)
    env = os.environ.copy()
    for name in ("PGPASSWORD", "PGHOSTADDR", "PGSERVICE", "PGOPTIONS"):
        env.pop(name, None)
    env.update(
        PGHOST=str(directory / "socket"),
        PGPORT="16544",
        PGDATABASE="postgres",
        PGUSER=config["restore_superuser"],
        PGCONNECT_TIMEOUT="5",
    )
    sql = """
SELECT json_build_object(
 'in_recovery',pg_is_in_recovery(),
 'paused',pg_get_wal_replay_pause_state(),
 'system_id',(SELECT system_identifier::text FROM pg_control_system()),
 'before_role',EXISTS(SELECT FROM pg_roles WHERE rolname='%s'),
 'after_role',EXISTS(SELECT FROM pg_roles WHERE rolname='%s'));
""" % (probe["before_role"], probe["after_role"])
    command = [
        str(Path(config["pg_bin"]) / "psql"),
        "-X",
        "-At",
        "--no-password",
        "-v",
        "ON_ERROR_STOP=1",
        "-c",
        sql,
    ]
    result = json.loads(checked(command, env=env))
    if not (
        result["in_recovery"]
        and result["paused"] == "paused"
        and result["before_role"]
        and not result["after_role"]
        and result["system_id"] == str(config["system_id"])
    ):
        raise RuntimeError("PITR target proof failed")
    # Loading PostGIS is part of compatibility proof, not just server startup.
    checked(
        command[:-1] + ["SELECT postgis_lib_version();"],
        env=env | {"PGDATABASE": config["application_database"]},
    )
    atomic_json(
        directory / "verified.json",
        result
        | {
            "target_time": probe["target_time"],
            "postgis_loaded": True,
        },
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "verify"))
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--probe", type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    config = load_config(args.config)
    if args.action == "prepare":
        if not args.probe:
            parser.error("--probe is required")
        memory_headroom(3 * 1024**3)
        directory = prepare(
            config,
            json.loads(args.probe.read_text()),
            "/etc/ugc-pitr/pitr.identity",
        )
        print(json.dumps({"prepared": str(directory)}))
    else:
        print(json.dumps(verify(config, RESTORE_ROOT / "current")))


if __name__ == "__main__":
    main()
