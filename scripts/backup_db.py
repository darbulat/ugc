#!/usr/bin/env python3
"""Script for creating PostgreSQL database backup."""

import argparse
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


def create_backup(
    host: str,
    port: int,
    database: str,
    user: str,
    password: str,
    output_dir: Path,
    compress: bool = True,
) -> Path:
    """
    Create PostgreSQL database backup using pg_dump.

    Args:
        host: Database host
        port: Database port
        database: Database name
        user: Database user
        password: Database password
        output_dir: Directory to save backup
        compress: Whether to compress backup with gzip

    Returns:
        Path to created backup file

    Raises:
        subprocess.CalledProcessError: If pg_dump fails
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_filename = f"ugc_backup_{timestamp}.sql"
    if compress:
        backup_filename += ".gz"

    output_dir.mkdir(parents=True, exist_ok=True)
    backup_path = output_dir / backup_filename

    # Set PGPASSWORD environment variable for pg_dump
    env = os.environ.copy()
    env["PGPASSWORD"] = password

    pg_dump_cmd = [
        "pg_dump",
        "-h",
        host,
        "-p",
        str(port),
        "-U",
        user,
        "-d",
        database,
        "--no-owner",
        "--no-acl",
        "--clean",
        "--if-exists",
    ]

    try:
        if compress:
            # Use gzip compression
            with open(backup_path, "wb") as f:
                dump_process = subprocess.Popen(
                    pg_dump_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=env,
                )
                gzip_process = subprocess.Popen(
                    ["gzip"],
                    stdin=dump_process.stdout,
                    stdout=f,
                )
                dump_process.stdout.close()
                gzip_process.communicate()
                dump_process.wait()
                if dump_process.returncode != 0:
                    stderr = dump_process.stderr.read().decode()
                    raise subprocess.CalledProcessError(
                        dump_process.returncode,
                        pg_dump_cmd,
                        stderr=stderr,
                    )
        else:
            # No compression
            with open(backup_path, "w") as f:
                result = subprocess.run(
                    pg_dump_cmd,
                    stdout=f,
                    stderr=subprocess.PIPE,
                    env=env,
                    check=True,
                )

        print(f"Backup created successfully: {backup_path}")
        return backup_path

    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.decode() if e.stderr else str(e)
        print(f"Error creating backup: {error_msg}", file=sys.stderr)
        if backup_path.exists():
            backup_path.unlink()
        raise


def cleanup_old_backups(output_dir: Path, keep_days: int = 7) -> None:
    """
    Remove backup files older than specified days.

    Args:
        output_dir: Directory with backup files
        keep_days: Number of days to keep backups
    """
    if not output_dir.exists():
        return

    cutoff_time = datetime.now().timestamp() - (keep_days * 24 * 60 * 60)

    removed_count = 0
    for backup_file in output_dir.glob("ugc_backup_*.sql*"):
        if backup_file.stat().st_mtime < cutoff_time:
            backup_file.unlink()
            removed_count += 1

    if removed_count > 0:
        print(f"Removed {removed_count} old backup(s)")


def _get_s3_config() -> dict | None:
    """
    Read S3 configuration from environment.

    Returns:
        Dict with endpoint_url, bucket, access_key, secret_key if S3 backup
        is enabled and all required vars are set; None otherwise.
    """
    if os.getenv("S3_BACKUP_ENABLED", "").lower() not in ("1", "true", "yes"):
        return None
    endpoint = os.getenv("S3_ENDPOINT_URL", "https://s3.ru1.storage.beget.cloud")
    bucket = os.getenv("S3_BUCKET", "97596cccd207-ugc-s3")
    access_key = os.getenv("S3_ACCESS_KEY_ID", "").strip()
    secret_key = os.getenv("S3_SECRET_ACCESS_KEY", "").strip()
    if not access_key or not secret_key:
        logger.warning("S3 backup enabled but S3_ACCESS_KEY_ID or S3_SECRET_ACCESS_KEY missing")
        return None
    return {
        "endpoint_url": endpoint,
        "bucket": bucket,
        "access_key": access_key,
        "secret_key": secret_key,
    }


def upload_backup_to_s3(backup_path: Path, s3_config: dict) -> bool:
    """
    Upload backup file to S3 using path-style addressing (e.g. Beget).

    Args:
        backup_path: Path to the backup file.
        s3_config: Dict with endpoint_url, bucket, access_key, secret_key.

    Returns:
        True if upload succeeded, False otherwise.
    """
    try:
        import boto3
        from botocore.config import Config
    except ImportError as e:
        logger.warning("boto3 not available, skipping S3 upload: %s", e)
        return False

    try:
        config = Config(s3={"addressing_style": "path"})
        client = boto3.client(
            "s3",
            endpoint_url=s3_config["endpoint_url"],
            aws_access_key_id=s3_config["access_key"],
            aws_secret_access_key=s3_config["secret_key"],
            config=config,
        )
        key = f"backups/{backup_path.name}"
        client.upload_file(str(backup_path), s3_config["bucket"], key)
        print(f"Uploaded to S3: s3://{s3_config['bucket']}/{key}")
        return True
    except Exception as e:
        logger.exception("S3 upload failed: %s", e)
        print(f"Warning: S3 upload failed: {e}", file=sys.stderr)
        return False


def cleanup_old_s3_backups(
    s3_config: dict,
    prefix: str = "backups/",
    keep_days: int = 7,
) -> None:
    """
    Remove backup objects in S3 older than keep_days.

    Args:
        s3_config: Dict with endpoint_url, bucket, access_key, secret_key.
        prefix: S3 key prefix to list (e.g. backups/).
        keep_days: Number of days to keep backups.
    """
    try:
        import boto3
        from botocore.config import Config
    except ImportError:
        return

    try:
        config = Config(s3={"addressing_style": "path"})
        client = boto3.client(
            "s3",
            endpoint_url=s3_config["endpoint_url"],
            aws_access_key_id=s3_config["access_key"],
            aws_secret_access_key=s3_config["secret_key"],
            config=config,
        )
        cutoff = datetime.now().timestamp() - (keep_days * 24 * 60 * 60)
        paginator = client.get_paginator("list_objects_v2")
        to_delete = []
        for page in paginator.paginate(Bucket=s3_config["bucket"], Prefix=prefix):
            for obj in page.get("Contents") or []:
                if obj.get("LastModified"):
                    if obj["LastModified"].timestamp() < cutoff:
                        to_delete.append({"Key": obj["Key"]})
        if to_delete:
            for i in range(0, len(to_delete), 1000):
                chunk = to_delete[i : i + 1000]
                client.delete_objects(
                    Bucket=s3_config["bucket"],
                    Delete={"Objects": chunk, "Quiet": True},
                )
            print(f"Removed {len(to_delete)} old backup(s) from S3")
    except Exception as e:
        logger.warning("S3 cleanup failed: %s", e)
        print(f"Warning: S3 cleanup failed: {e}", file=sys.stderr)


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Create PostgreSQL database backup")
    parser.add_argument(
        "--host",
        default=os.getenv("POSTGRES_HOST", "localhost"),
        help="Database host (default: POSTGRES_HOST env or localhost)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("POSTGRES_PORT", "5432")),
        help="Database port (default: POSTGRES_PORT env or 5432)",
    )
    parser.add_argument(
        "--database",
        default=os.getenv("POSTGRES_DB", "ugc"),
        help="Database name (default: POSTGRES_DB env or ugc)",
    )
    parser.add_argument(
        "--user",
        default=os.getenv("POSTGRES_USER", "ugc"),
        help="Database user (default: POSTGRES_USER env or ugc)",
    )
    parser.add_argument(
        "--password",
        default=os.getenv("POSTGRES_PASSWORD", ""),
        help="Database password (default: POSTGRES_PASSWORD env)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(os.getenv("BACKUP_DIR", "/backups")),
        help="Output directory for backups (default: BACKUP_DIR env or /backups)",
    )
    parser.add_argument(
        "--no-compress",
        action="store_true",
        help="Disable gzip compression",
    )
    parser.add_argument(
        "--cleanup-days",
        type=int,
        default=int(os.getenv("BACKUP_KEEP_DAYS", "7")),
        help="Remove backups older than N days (default: BACKUP_KEEP_DAYS env or 7)",
    )

    args = parser.parse_args()

    if not args.password:
        print("Error: Database password is required", file=sys.stderr)
        sys.exit(1)

    try:
        backup_path = create_backup(
            host=args.host,
            port=args.port,
            database=args.database,
            user=args.user,
            password=args.password,
            output_dir=args.output_dir,
            compress=not args.no_compress,
        )
        print(f"Backup size: {backup_path.stat().st_size / 1024 / 1024:.2f} MB")

        if args.cleanup_days > 0:
            cleanup_old_backups(args.output_dir, args.cleanup_days)

        s3_config = _get_s3_config()
        if s3_config:
            upload_backup_to_s3(backup_path, s3_config)
            if args.cleanup_days > 0:
                cleanup_old_s3_backups(
                    s3_config,
                    prefix="backups/",
                    keep_days=args.cleanup_days,
                )

        sys.exit(0)

    except subprocess.CalledProcessError:
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
