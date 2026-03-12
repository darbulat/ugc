#!/usr/bin/env python3
"""Upload archived WAL segments from local directory to S3.

Scans WAL_ARCHIVE_DIR for files, uploads each to S3 under the
``wal_archive/`` prefix, and removes the local copy after successful
upload.  Designed to be called periodically from backup_loop.sh.
"""

import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def _get_s3_config() -> dict | None:
    """Read S3 config from environment (same vars as backup_db)."""
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
        logger.warning(
            "S3 backup enabled but S3 credentials missing",
        )
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


def upload_wal_files(
    wal_dir: Path,
    s3_config: dict,
    prefix: str = "wal_archive/",
    remove_after_upload: bool = True,
) -> int:
    """Upload WAL segment files from *wal_dir* to S3.

    Returns:
        Number of files successfully uploaded.
    """
    if not wal_dir.exists():
        return 0

    client = _create_s3_client(s3_config)
    uploaded = 0

    for wal_file in sorted(wal_dir.iterdir()):
        if not wal_file.is_file():
            continue
        if wal_file.name.endswith(".partial"):
            continue

        key = f"{prefix}{wal_file.name}"
        try:
            with open(wal_file, "rb") as f:
                body = f.read()
            client.put_object(
                Bucket=s3_config["bucket"],
                Key=key,
                Body=body,
            )
            uploaded += 1
            logger.info(
                "Uploaded WAL %s to S3 (%s)",
                wal_file.name,
                key,
            )
            if remove_after_upload:
                wal_file.unlink()
        except Exception:
            logger.exception(
                "Failed to upload WAL %s",
                wal_file.name,
            )

    return uploaded


def cleanup_old_wal_s3(
    s3_config: dict,
    prefix: str = "wal_archive/",
    keep_days: int = 7,
) -> int:
    """Remove WAL objects in S3 older than *keep_days*.

    Returns:
        Number of objects deleted.
    """
    from datetime import datetime

    client = _create_s3_client(s3_config)
    cutoff = datetime.now().timestamp() - (keep_days * 86400)
    paginator = client.get_paginator("list_objects_v2")
    to_delete: list[dict[str, str]] = []

    bucket = s3_config["bucket"]
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents") or []:
            last_mod = obj.get("LastModified")
            if last_mod and last_mod.timestamp() < cutoff:
                to_delete.append({"Key": obj["Key"]})

    deleted = 0
    for i in range(0, len(to_delete), 1000):
        chunk = to_delete[i : i + 1000]
        client.delete_objects(
            Bucket=bucket,
            Delete={"Objects": chunk, "Quiet": True},
        )
        deleted += len(chunk)

    if deleted:
        print(f"Removed {deleted} old WAL file(s) from S3")
    return deleted


def main() -> None:
    """Upload WAL files from WAL_ARCHIVE_DIR to S3."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    wal_dir = Path(os.getenv("WAL_ARCHIVE_DIR", "/wal_archive"))
    keep_days = int(os.getenv("BACKUP_KEEP_DAYS", "7"))

    s3_config = _get_s3_config()
    if not s3_config:
        logger.info("S3 not enabled, skipping WAL upload")
        sys.exit(0)

    uploaded = upload_wal_files(wal_dir, s3_config)
    if uploaded:
        print(f"Uploaded {uploaded} WAL file(s) to S3")

    cleanup_old_wal_s3(s3_config, keep_days=keep_days)


if __name__ == "__main__":
    main()
