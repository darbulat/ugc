#!/usr/bin/env python3
"""Upload PostgreSQL WAL segment to S3 for Point-in-Time Recovery (PITR).

Invoked by PostgreSQL archive_command with two arguments: %p (full path to WAL file)
and %f (WAL file name). Uploads the file to S3 under wal_archive/ prefix.
Exits 0 on success, non-zero on failure (so PostgreSQL will retry archiving).
"""

import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

WAL_ARCHIVE_PREFIX = "wal_archive"


def _get_s3_config() -> dict | None:
    """Read S3 configuration from environment for WAL archiving."""
    endpoint = os.getenv("S3_ENDPOINT_URL", "https://s3.ru1.storage.beget.cloud").strip()
    bucket = os.getenv("S3_BUCKET", "97596cccd207-ugc-s3").strip()
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


def upload_wal_to_s3(wal_path: Path, s3_key: str, s3_config: dict) -> bool:
    """Upload WAL file to S3. Returns True on success, False otherwise."""
    try:
        import boto3
        from botocore.config import Config
    except ImportError as e:
        logger.error("boto3 not available: %s", e)
        return False

    try:
        config = Config(
            s3={
                "addressing_style": "path",
                "payload_signing_enabled": False,
            },
        )
        client = boto3.client(
            "s3",
            endpoint_url=s3_config["endpoint_url"],
            aws_access_key_id=s3_config["access_key"],
            aws_secret_access_key=s3_config["secret_key"],
            config=config,
        )
        with open(wal_path, "rb") as f:
            body = f.read()
        client.put_object(Bucket=s3_config["bucket"], Key=s3_key, Body=body)
        logger.info("Archived WAL to s3://%s/%s", s3_config["bucket"], s3_key)
        return True
    except Exception as e:
        logger.exception("WAL upload to S3 failed: %s", e)
        return False


def main() -> int:
    """Entry point for archive_command. Returns 0 on success, 1 on failure."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    if len(sys.argv) != 3:
        logger.error("Usage: archive_wal.py <wal_path> <wal_filename>")
        return 1

    wal_path = Path(sys.argv[1])
    wal_filename = sys.argv[2]

    if not wal_path.is_file():
        logger.error("WAL file not found: %s", wal_path)
        return 1

    s3_config = _get_s3_config()
    if not s3_config:
        logger.error(
            "S3 credentials required: set S3_ACCESS_KEY_ID and S3_SECRET_ACCESS_KEY"
        )
        return 1

    prefix = os.getenv("WAL_ARCHIVE_S3_PREFIX", WAL_ARCHIVE_PREFIX).strip()
    s3_key = f"{prefix}/{wal_filename}"

    if upload_wal_to_s3(wal_path, s3_key, s3_config):
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
