#!/usr/bin/env python3
"""Create PostgreSQL base backup (pg_basebackup) and upload to S3 for PITR.

Used together with WAL archiving to enable Point-in-Time Recovery.
Run periodically (e.g. daily) from db_backup service or cron.
"""

import argparse
import logging
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

logger = logging.getLogger(__name__)

BASE_BACKUP_S3_PREFIX = "base_backup"


def _parse_database_url(url: str) -> dict[str, str | int] | None:
    """
    Parse PostgreSQL DATABASE_URL into host, port, database, user, password.

    Supports postgresql:// and postgresql+psycopg://. Returns None if URL
    is empty, invalid or not PostgreSQL.
    """
    url = (url or "").strip()
    if not url:
        return None
    try:
        parsed = urlparse(url)
    except Exception:
        return None
    if not parsed.scheme or not parsed.scheme.startswith("postgresql"):
        return None
    hostname = parsed.hostname or "localhost"
    port = parsed.port if parsed.port is not None else 5432
    path = (parsed.path or "").strip("/")
    database = path or "ugc"
    user = unquote(parsed.username) if parsed.username else ""
    password = unquote(parsed.password) if parsed.password else ""
    return {
        "host": hostname,
        "port": port,
        "database": database,
        "user": user,
        "password": password,
    }


def _get_s3_config() -> dict | None:
    """Read S3 configuration from environment."""
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


def create_base_backup(
    host: str,
    port: int,
    user: str,
    password: str,
    output_path: Path,
) -> Path:
    """
    Run pg_basebackup and write compressed tar to output_path.

    Returns:
        Path to the created .tar.gz file.

    Raises:
        subprocess.CalledProcessError: If pg_basebackup or gzip fails.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["PGPASSWORD"] = password

    with tempfile.TemporaryDirectory(prefix="pg_basebackup_") as tmpdir:
        tmpdir_path = Path(tmpdir)
        # -Ft tar -z writes base.tar.gz (and pg_wal.tar.gz if -X fetch) into -D
        subprocess.run(
            [
                "pg_basebackup",
                "-h",
                host,
                "-p",
                str(port),
                "-U",
                user,
                "-D",
                str(tmpdir_path),
                "-Ft",
                "-z",
                "-X",
                "fetch",
            ],
            env=env,
            check=True,
            capture_output=True,
        )
        # PG 15+ with -z produces base.tar.gz; older PG produces base.tar
        base_tar_gz = tmpdir_path / "base.tar.gz"
        base_tar = tmpdir_path / "base.tar"
        if base_tar_gz.exists():
            base_tar_gz.rename(output_path)
        elif base_tar.exists():
            with open(output_path, "wb") as f:
                subprocess.run(
                    ["gzip", "-c", str(base_tar)],
                    stdout=f,
                    check=True,
                )
        else:
            archive = next(
                (f for f in tmpdir_path.iterdir() if f.name.startswith("base")),
                None,
            )
            if archive is None:
                raise FileNotFoundError(
                    f"No base backup archive found in {tmpdir_path}"
                )
            archive.rename(output_path)

    return output_path


def upload_base_backup_to_s3(local_path: Path, s3_key: str, s3_config: dict) -> bool:
    """Upload base backup file to S3. Returns True on success."""
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
        with open(local_path, "rb") as f:
            client.put_object(
                Bucket=s3_config["bucket"],
                Key=s3_key,
                Body=f.read(),
            )
        logger.info(
            "Uploaded base backup to s3://%s/%s",
            s3_config["bucket"],
            s3_key,
        )
        return True
    except Exception as e:
        logger.exception("Base backup upload failed: %s", e)
        return False


def list_base_backups_s3(
    s3_config: dict, prefix_key: str
) -> list[tuple[str, datetime]]:
    """List base backup keys in S3 under prefix, newest first. Returns [(key, last_modified), ...]."""
    try:
        import boto3
        from botocore.config import Config
    except ImportError:
        return []

    config = Config(
        s3={"addressing_style": "path", "payload_signing_enabled": False},
    )
    client = boto3.client(
        "s3",
        endpoint_url=s3_config["endpoint_url"],
        aws_access_key_id=s3_config["access_key"],
        aws_secret_access_key=s3_config["secret_key"],
        config=config,
    )
    s3_prefix = prefix_key.rstrip("/") + "/"
    result: list[tuple[str, datetime]] = []
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=s3_config["bucket"], Prefix=s3_prefix):
        for obj in page.get("Contents") or []:
            key = obj.get("Key")
            last_mod = obj.get("LastModified")
            if key and key.endswith(".tar.gz") and last_mod:
                result.append((key, last_mod))
    result.sort(key=lambda x: x[1], reverse=True)
    return result


def cleanup_old_base_backups_s3(
    s3_config: dict,
    prefix: str,
    keep_days: int,
) -> None:
    """Remove base backup objects in S3 older than keep_days."""
    try:
        import boto3
        from botocore.config import Config
    except ImportError:
        return

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
            print(f"Removed {len(to_delete)} old base backup(s) from S3")
    except Exception as e:
        logger.warning("S3 base backup cleanup failed: %s", e)
        print(f"Warning: S3 base backup cleanup failed: {e}", file=sys.stderr)


def main() -> int:
    """Main entry point. Returns 0 on success, 1 on failure."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    db_from_url = _parse_database_url(os.getenv("DATABASE_URL", ""))
    postgres_host = os.getenv("POSTGRES_HOST", "").strip()
    postgres_port = os.getenv("POSTGRES_PORT", "").strip()
    postgres_user = os.getenv("POSTGRES_USER", "").strip()
    postgres_password = os.getenv("POSTGRES_PASSWORD", "").strip()

    if db_from_url:
        defaults = {
            "host": db_from_url["host"],
            "port": int(db_from_url["port"]),
            "user": db_from_url["user"],
            "password": db_from_url["password"] or postgres_password,
        }
    else:
        defaults = {
            "host": postgres_host or "localhost",
            "port": int(postgres_port) if postgres_port else 5432,
            "user": postgres_user or "ugc",
            "password": postgres_password,
        }
    if postgres_host:
        defaults["host"] = postgres_host
    if postgres_port:
        defaults["port"] = int(postgres_port)
    if postgres_user:
        defaults["user"] = postgres_user
    if postgres_password:
        defaults["password"] = postgres_password

    parser = argparse.ArgumentParser(
        description="Create PostgreSQL base backup and upload to S3 for PITR"
    )
    parser.add_argument(
        "--host",
        default=defaults["host"],
        help="Database host",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=defaults["port"],
        help="Database port",
    )
    parser.add_argument(
        "--user",
        default=defaults["user"],
        help="Database user",
    )
    parser.add_argument(
        "--password",
        default=defaults["password"],
        help="Database password",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(os.getenv("BACKUP_DIR", "/backups")),
        help="Temporary output directory for base backup before upload",
    )
    parser.add_argument(
        "--cleanup-days",
        type=int,
        default=int(os.getenv("BASE_BACKUP_KEEP_DAYS", os.getenv("BACKUP_KEEP_DAYS", "7"))),
        help="Remove base backups in S3 older than N days",
    )
    parser.add_argument(
        "--list-s3",
        action="store_true",
        help="List base backups in S3 and exit (requires S3_* env vars)",
    )
    args = parser.parse_args()

    if args.list_s3:
        s3_config = _get_s3_config()
        if not s3_config:
            print(
                "Error: S3 credentials required. Set S3_ACCESS_KEY_ID and S3_SECRET_ACCESS_KEY.",
                file=sys.stderr,
            )
            return 1
        prefix = os.getenv("BASE_BACKUP_S3_PREFIX", BASE_BACKUP_S3_PREFIX).strip()
        backups = list_base_backups_s3(s3_config, prefix)
        if not backups:
            print("No base backups found in S3.")
            return 0
        print("Base backups in S3 (newest first):")
        for key, last_mod in backups:
            print(f"  {key}  ({last_mod})")
        return 0

    if not args.password:
        print("Error: Database password is required", file=sys.stderr)
        return 1

    s3_config = _get_s3_config()
    if not s3_config:
        print(
            "Error: S3 credentials required for base backup. "
            "Set S3_ACCESS_KEY_ID and S3_SECRET_ACCESS_KEY.",
            file=sys.stderr,
        )
        return 1

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_filename = f"ugc_base_{timestamp}.tar.gz"
    local_path = args.output_dir / backup_filename
    prefix = os.getenv("BASE_BACKUP_S3_PREFIX", BASE_BACKUP_S3_PREFIX).strip()
    s3_key = f"{prefix}/{backup_filename}"

    try:
        create_base_backup(
            host=args.host,
            port=args.port,
            user=args.user,
            password=args.password,
            output_path=local_path,
        )
        size_mb = local_path.stat().st_size / (1024 * 1024)
        print(f"Base backup created: {local_path} ({size_mb:.2f} MB)")

        if not upload_base_backup_to_s3(local_path, s3_key, s3_config):
            return 1
        print(f"Uploaded to S3: s3://{s3_config['bucket']}/{s3_key}")

        if args.cleanup_days > 0:
            cleanup_old_base_backups_s3(
                s3_config,
                prefix=prefix + "/",
                keep_days=args.cleanup_days,
            )

        if local_path.exists():
            local_path.unlink()
        return 0

    except subprocess.CalledProcessError as e:
        logger.exception("pg_basebackup failed: %s", e)
        if local_path.exists():
            local_path.unlink(missing_ok=True)
        return 1
    except Exception as e:
        logger.exception("Unexpected error: %s", e)
        if local_path.exists():
            local_path.unlink(missing_ok=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
