#!/usr/bin/env python3
"""Point-in-Time Recovery (PITR) helper.

Downloads the latest (or specified) base backup and WAL segments from
S3, extracts the base backup into a target PGDATA directory, and writes
``recovery.signal`` + ``restore_command`` in ``postgresql.auto.conf`` so
PostgreSQL replays WAL on next startup.

Usage (inside the ``db`` container or with PGDATA access)::

    python scripts/pitr_restore.py \\
        --target-time "2025-06-01 12:00:00" \\
        --pgdata /var/lib/postgresql/data \\
        --confirm
"""

import argparse
import contextlib
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

_RECOVERY_PARAMS = (
    "restore_command",
    "recovery_target_time",
    "recovery_target_action",
)


def _create_s3_client(s3_config: dict):
    """Create boto3 S3 client with path-style addressing."""
    import boto3
    from botocore.config import Config

    config = Config(
        s3={
            "addressing_style": "path",
            "payload_signing_enabled": False,
        },
    )
    return boto3.client(
        "s3",
        endpoint_url=s3_config["endpoint_url"],
        aws_access_key_id=s3_config["access_key"],
        aws_secret_access_key=s3_config["secret_key"],
        config=config,
    )


def _get_s3_config() -> dict | None:
    """Read S3 configuration from environment."""
    endpoint = os.getenv(
        "S3_ENDPOINT_URL",
        "https://s3.ru1.storage.beget.cloud",
    )
    bucket = os.getenv("S3_BUCKET", "97596cccd207-ugc-s3")
    access_key = os.getenv("S3_ACCESS_KEY_ID", "").strip()
    secret_key = os.getenv("S3_SECRET_ACCESS_KEY", "").strip()
    if not access_key or not secret_key:
        return None
    return {
        "endpoint_url": endpoint,
        "bucket": bucket,
        "access_key": access_key,
        "secret_key": secret_key,
    }


def list_base_backups(s3_config: dict) -> list[str]:
    """List available base backups in S3 (newest first)."""
    client = _create_s3_client(s3_config)
    paginator = client.get_paginator("list_objects_v2")
    keys_with_ts: list[tuple[str, object]] = []
    bucket = s3_config["bucket"]
    for page in paginator.paginate(
        Bucket=bucket, Prefix="base_backups/",
    ):
        for obj in page.get("Contents") or []:
            key = obj.get("Key")
            if key and key.endswith(".tar.gz"):
                last_mod = obj.get("LastModified")
                if last_mod is not None:
                    keys_with_ts.append((key, last_mod))
    keys_with_ts.sort(key=lambda x: x[1], reverse=True)
    return [k for k, _ in keys_with_ts]


def download_s3_file(
    s3_config: dict,
    key: str,
    dest: Path,
) -> Path:
    """Download an S3 object to a local file."""
    client = _create_s3_client(s3_config)
    client.download_file(s3_config["bucket"], key, str(dest))
    logger.info(
        "Downloaded s3://%s/%s -> %s",
        s3_config["bucket"],
        key,
        dest,
    )
    return dest


def download_wal_files(s3_config: dict, wal_dir: Path) -> int:
    """Download all WAL files from S3 into *wal_dir*.

    Returns number of WAL files downloaded.
    """
    wal_dir.mkdir(parents=True, exist_ok=True)
    client = _create_s3_client(s3_config)
    paginator = client.get_paginator("list_objects_v2")
    bucket = s3_config["bucket"]
    count = 0
    for page in paginator.paginate(
        Bucket=bucket, Prefix="wal_archive/",
    ):
        for obj in page.get("Contents") or []:
            key = obj.get("Key", "")
            name = key.split("/")[-1]
            if not name:
                continue
            dest = wal_dir / name
            if dest.exists():
                continue
            client.download_file(bucket, key, str(dest))
            count += 1
    logger.info("Downloaded %d WAL file(s) to %s", count, wal_dir)
    return count


def extract_base_backup(archive_path: Path, pgdata: Path) -> None:
    """Extract base backup tar.gz into *pgdata*."""
    pgdata.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["tar", "xzf", str(archive_path), "-C", str(pgdata)],
        check=True,
    )
    logger.info("Extracted base backup to %s", pgdata)


def configure_recovery(
    pgdata: Path,
    wal_dir: Path,
    target_time: str | None = None,
) -> None:
    """Write recovery config for PostgreSQL WAL replay.

    Creates ``recovery.signal`` and appends restore_command (and
    optionally recovery_target_time) to ``postgresql.auto.conf``.
    """
    (pgdata / "recovery.signal").touch()

    auto_conf = pgdata / "postgresql.auto.conf"
    lines: list[str] = []
    if auto_conf.exists():
        lines = auto_conf.read_text().splitlines()

    # Remove previous recovery settings
    lines = [
        line
        for line in lines
        if not line.strip().startswith(_RECOVERY_PARAMS)
    ]

    restore_cmd = f"restore_command = 'cp {wal_dir}/%f %p'"
    lines.append(restore_cmd)

    if target_time:
        lines.append(f"recovery_target_time = '{target_time}'")
        lines.append("recovery_target_action = 'promote'")

    auto_conf.write_text("\n".join(lines) + "\n")
    logger.info("Recovery config written to %s", auto_conf)
    print(f"restore_command = 'cp {wal_dir}/%f %p'")
    if target_time:
        print(f"recovery_target_time = '{target_time}'")


def _run_restore(args: argparse.Namespace, s3_config: dict) -> None:
    """Execute the PITR restore procedure."""
    base_key = args.base_backup
    if not base_key:
        backups = list_base_backups(s3_config)
        if not backups:
            print("Error: No base backups in S3.", file=sys.stderr)
            sys.exit(1)
        base_key = backups[0]
        print(f"Using latest base backup: {base_key}")

    tmp = Path(tempfile.mkdtemp())
    archive_path = tmp / "base_backup.tar.gz"
    try:
        print("Downloading base backup from S3...")
        download_s3_file(s3_config, base_key, archive_path)

        print("Downloading WAL files from S3...")
        download_wal_files(s3_config, args.wal_dir)

        print(f"Extracting base backup to {args.pgdata}...")
        extract_base_backup(archive_path, args.pgdata)

        print("Configuring recovery...")
        configure_recovery(
            args.pgdata, args.wal_dir, args.target_time,
        )

        print("\nPITR restore prepared successfully!")
        print("Next steps:")
        print("  1. Start PostgreSQL (recovery mode)")
        print("  2. Monitor pg_is_in_recovery()")
        print("  3. PostgreSQL auto-promotes after replay")
    finally:
        if archive_path.exists():
            archive_path.unlink()
        if tmp.exists():
            with contextlib.suppress(OSError):
                tmp.rmdir()


def main() -> None:
    """PITR restore entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        description="PITR from S3 base backup + WAL",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        dest="list_backups",
        help="List base backups in S3 and exit",
    )
    parser.add_argument(
        "--base-backup",
        default=None,
        help="S3 key of base backup (default: latest)",
    )
    parser.add_argument(
        "--target-time",
        default=None,
        help="Recovery target, e.g. '2025-06-01 12:00:00'",
    )
    parser.add_argument(
        "--pgdata",
        type=Path,
        default=Path(
            os.getenv("PGDATA", "/var/lib/postgresql/data"),
        ),
    )
    parser.add_argument(
        "--wal-dir",
        type=Path,
        default=Path(os.getenv("WAL_RESTORE_DIR", "/wal_restore")),
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Skip confirmation prompt",
    )
    args = parser.parse_args()

    s3_config = _get_s3_config()
    if not s3_config:
        print(
            "Error: S3 credentials required. "
            "Set S3_ACCESS_KEY_ID and S3_SECRET_ACCESS_KEY.",
            file=sys.stderr,
        )
        sys.exit(1)

    if args.list_backups:
        backups = list_base_backups(s3_config)
        if not backups:
            print("No base backups found in S3.")
        else:
            print("Available base backups (newest first):")
            for k in backups:
                print(f"  {k}")
        sys.exit(0)

    if not args.confirm:
        response = input(
            f"WARNING: This will overwrite '{args.pgdata}'. "
            "PostgreSQL MUST be stopped. Continue? (yes/no): "
        )
        if response.lower() != "yes":
            print("PITR restore cancelled.")
            sys.exit(0)

    _run_restore(args, s3_config)


if __name__ == "__main__":
    main()
