#!/usr/bin/env python3
"""Create a physical base backup using pg_basebackup.

Optionally uploads the result to S3.  The resulting tar.gz archive is
stored locally and (if S3 is enabled) uploaded under the
``base_backups/`` prefix.  Old base backups are rotated by
``BACKUP_KEEP_DAYS``.
"""

import argparse
import logging
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


def create_base_backup(
    host: str,
    port: int,
    user: str,
    password: str,
    output_dir: Path,
) -> Path:
    """Run ``pg_basebackup`` and produce a compressed tar.

    Returns:
        Path to the created ``.tar.gz`` file.

    Raises:
        subprocess.CalledProcessError: If pg_basebackup fails.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"ugc_basebackup_{timestamp}.tar.gz"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / filename

    env = os.environ.copy()
    env["PGPASSWORD"] = password

    cmd = [
        "pg_basebackup",
        "-h", host,
        "-p", str(port),
        "-U", user,
        "-D", "-",
        "--format=tar",
        "--gzip",
        "--checkpoint=fast",
        "--wal-method=none",
    ]

    try:
        with open(output_path, "wb") as f:
            subprocess.run(
                cmd,
                stdout=f,
                stderr=subprocess.PIPE,
                env=env,
                check=True,
            )
        size_mb = output_path.stat().st_size / (1024 * 1024)
        print(f"Base backup created: {output_path} ({size_mb:.2f} MB)")
        return output_path
    except subprocess.CalledProcessError as e:
        stderr = e.stderr
        error_msg = (
            stderr.decode()
            if isinstance(stderr, bytes)
            else (stderr or str(e))
        )
        print(
            f"Error creating base backup: {error_msg}",
            file=sys.stderr,
        )
        if output_path.exists():
            output_path.unlink()
        raise


def cleanup_old_base_backups(
    output_dir: Path,
    keep_days: int = 7,
) -> None:
    """Remove local base backup files older than *keep_days*."""
    if not output_dir.exists():
        return
    cutoff = datetime.now().timestamp() - (keep_days * 86400)
    removed = 0
    for f in output_dir.glob("ugc_basebackup_*.tar.gz"):
        if f.stat().st_mtime < cutoff:
            f.unlink()
            removed += 1
    if removed:
        print(f"Removed {removed} old base backup(s)")


def _get_s3_config() -> dict | None:
    """Read S3 configuration from environment."""
    enabled = os.getenv("S3_BACKUP_ENABLED", "").lower()
    if enabled not in ("1", "true", "yes"):
        return None
    endpoint = os.getenv(
        "S3_ENDPOINT_URL",
        "https://s3.ru1.storage.beget.cloud",
    )
    bucket = os.getenv("S3_BUCKET", "97596cccd207-ugc-s3")
    access_key = os.getenv("S3_ACCESS_KEY_ID", "").strip()
    secret_key = os.getenv("S3_SECRET_ACCESS_KEY", "").strip()
    if not access_key or not secret_key:
        logger.warning("S3 enabled but credentials missing")
        return None
    return {
        "endpoint_url": endpoint,
        "bucket": bucket,
        "access_key": access_key,
        "secret_key": secret_key,
    }


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


def upload_base_backup_to_s3(
    backup_path: Path,
    s3_config: dict,
) -> bool:
    """Upload base backup archive to S3.

    Returns True on success, False otherwise.
    """
    try:
        client = _create_s3_client(s3_config)
        key = f"base_backups/{backup_path.name}"
        with open(backup_path, "rb") as f:
            body = f.read()
        client.put_object(
            Bucket=s3_config["bucket"],
            Key=key,
            Body=body,
        )
        bucket = s3_config["bucket"]
        print(f"Uploaded base backup to S3: s3://{bucket}/{key}")
        return True
    except Exception as e:
        logger.exception("S3 upload of base backup failed: %s", e)
        print(
            f"Warning: S3 upload failed: {e}",
            file=sys.stderr,
        )
        return False


def cleanup_old_base_backups_s3(
    s3_config: dict,
    prefix: str = "base_backups/",
    keep_days: int = 7,
) -> None:
    """Remove base backup objects in S3 older than *keep_days*."""
    try:
        client = _create_s3_client(s3_config)
        cutoff = datetime.now().timestamp() - (keep_days * 86400)
        paginator = client.get_paginator("list_objects_v2")
        to_delete: list[dict[str, str]] = []
        bucket = s3_config["bucket"]
        for page in paginator.paginate(
            Bucket=bucket, Prefix=prefix,
        ):
            for obj in page.get("Contents") or []:
                last_mod = obj.get("LastModified")
                if last_mod and last_mod.timestamp() < cutoff:
                    to_delete.append({"Key": obj["Key"]})
        if to_delete:
            for i in range(0, len(to_delete), 1000):
                chunk = to_delete[i : i + 1000]
                client.delete_objects(
                    Bucket=bucket,
                    Delete={"Objects": chunk, "Quiet": True},
                )
            n = len(to_delete)
            print(f"Removed {n} old base backup(s) from S3")
    except Exception as e:
        logger.warning("S3 cleanup failed: %s", e)
        print(f"Warning: S3 cleanup failed: {e}", file=sys.stderr)


def main() -> None:
    """Create base backup and optionally upload to S3."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    host = os.getenv("POSTGRES_HOST", "db")
    port = int(os.getenv("POSTGRES_PORT", "5432"))
    user = os.getenv("POSTGRES_USER", "ugc")
    password = os.getenv("POSTGRES_PASSWORD", "")

    parser = argparse.ArgumentParser(
        description="Create PostgreSQL base backup for PITR",
    )
    parser.add_argument("--host", default=host)
    parser.add_argument("--port", type=int, default=port)
    parser.add_argument("--user", default=user)
    parser.add_argument("--password", default=password)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(os.getenv("BASE_BACKUP_DIR", "/backups/base")),
    )
    parser.add_argument(
        "--cleanup-days",
        type=int,
        default=int(os.getenv("BACKUP_KEEP_DAYS", "7")),
    )
    args = parser.parse_args()

    if not args.password:
        print("Error: Database password is required", file=sys.stderr)
        sys.exit(1)

    try:
        backup_path = create_base_backup(
            host=args.host,
            port=args.port,
            user=args.user,
            password=args.password,
            output_dir=args.output_dir,
        )

        if args.cleanup_days > 0:
            cleanup_old_base_backups(
                args.output_dir, args.cleanup_days,
            )

        s3_config = _get_s3_config()
        if s3_config:
            upload_base_backup_to_s3(backup_path, s3_config)
            if args.cleanup_days > 0:
                cleanup_old_base_backups_s3(
                    s3_config, keep_days=args.cleanup_days,
                )

    except subprocess.CalledProcessError:
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
