#!/usr/bin/env python3
"""Script for restoring PostgreSQL database from backup."""

import argparse
import gzip
import logging
import os
import subprocess
import sys
import tempfile
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def _get_s3_config_restore() -> dict | None:
    """
    Read S3 configuration from environment for restore (no S3_BACKUP_ENABLED check).

    Returns:
        Dict with endpoint_url, bucket, access_key, secret_key if all required
        vars are set; None otherwise.
    """
    endpoint = os.getenv("S3_ENDPOINT_URL", "https://s3.ru1.storage.beget.cloud")
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


def _create_s3_client(s3_config: dict):
    """Create boto3 S3 client with path-style addressing (e.g. Beget)."""
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


def list_s3_backups(s3_config: dict, prefix: str = "backups/") -> list[str]:
    """
    List backup object keys in S3 under the given prefix.

    Args:
        s3_config: Dict with endpoint_url, bucket, access_key, secret_key.
        prefix: S3 key prefix to list (e.g. backups/).

    Returns:
        List of S3 object keys (newest first by LastModified).
    """
    client = _create_s3_client(s3_config)
    keys_with_ts: list[tuple[str, object]] = []
    keys_without_ts: list[str] = []
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=s3_config["bucket"], Prefix=prefix):
        for obj in page.get("Contents") or []:
            key = obj.get("Key")
            if key and (key.endswith(".sql") or key.endswith(".sql.gz")):
                last_mod = obj.get("LastModified")
                if last_mod is not None:
                    keys_with_ts.append((key, last_mod))
                else:
                    keys_without_ts.append(key)
    keys_with_ts.sort(key=lambda x: x[1], reverse=True)
    return [k for k, _ in keys_with_ts] + keys_without_ts


def download_backup_from_s3(s3_config: dict, key: str) -> Path:
    """
    Download backup file from S3 to a temporary file.

    Args:
        s3_config: Dict with endpoint_url, bucket, access_key, secret_key.
        key: S3 object key (e.g. backups/ugc_backup_20240206_020000.sql.gz).

    Returns:
        Path to the temporary file. Caller must unlink when done.

    Raises:
        FileNotFoundError: If the object does not exist.
        Exception: On download errors.
    """
    if not key.startswith("backups/"):
        key = f"backups/{key}"
    from botocore.exceptions import ClientError

    client = _create_s3_client(s3_config)
    try:
        response = client.get_object(Bucket=s3_config["bucket"], Key=key)
    except ClientError as e:
        if e.response.get("Error", {}).get("Code") == "NoSuchKey":
            raise FileNotFoundError(
                f"S3 object not found: s3://{s3_config['bucket']}/{key}"
            ) from e
        raise
    body = response["Body"].read()
    size_bytes = len(body)
    logger.info(
        "Downloaded from S3 s3://%s/%s: %d bytes (%.2f MiB)",
        s3_config["bucket"],
        key,
        size_bytes,
        size_bytes / (1024 * 1024),
    )
    suffix = ".sql.gz" if key.endswith(".sql.gz") else ".sql"
    fd, path = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(body)
        local_path = Path(path)
        logger.info("Saved to temporary file: %s", local_path)
        return local_path
    except Exception:
        os.unlink(path)
        raise


def restore_backup(
    host: str,
    port: int,
    database: str,
    user: str,
    password: str,
    backup_path: Path,
) -> None:
    """
    Restore PostgreSQL database from backup file.

    Args:
        host: Database host
        port: Database port
        database: Database name
        user: Database user
        password: Database password
        backup_path: Path to backup file

    Raises:
        FileNotFoundError: If backup file doesn't exist
        subprocess.CalledProcessError: If psql fails
    """
    if not backup_path.exists():
        raise FileNotFoundError(f"Backup file not found: {backup_path}")

    file_size = backup_path.stat().st_size
    logger.info(
        "Restoring to %s:%s database=%s (backup file: %s, %d bytes, %.2f MiB)",
        host,
        port,
        database,
        backup_path,
        file_size,
        file_size / (1024 * 1024),
    )
    if file_size == 0:
        logger.warning("Backup file is empty; restore may not change the database.")

    # Set PGPASSWORD environment variable for psql
    env = os.environ.copy()
    env["PGPASSWORD"] = password

    psql_cmd = [
        "psql",
        "-h",
        host,
        "-p",
        str(port),
        "-U",
        user,
        "-d",
        database,
        "-v",
        "ON_ERROR_STOP=1",
    ]
    logger.info("Running: psql -h %s -p %s -U %s -d %s ...", host, port, user, database)

    try:
        if backup_path.suffix == ".gz" or backup_path.name.endswith(".sql.gz"):
            # Decompress and restore; capture stderr to show NOTICEs and errors
            with gzip.open(backup_path, "rt") as f:
                result = subprocess.run(
                    psql_cmd,
                    stdin=f,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=env,
                )
        else:
            # Restore directly
            with open(backup_path, "r") as f:
                result = subprocess.run(
                    psql_cmd,
                    stdin=f,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=env,
                )

        if result.stderr:
            stderr_text = result.stderr.decode()
            logger.info("psql stderr output:\n%s", stderr_text.rstrip())
            print(stderr_text, file=sys.stderr, end="")

        if result.returncode != 0:
            error_msg = result.stderr.decode() if result.stderr else f"exit code {result.returncode}"
            logger.error("psql failed (exit %s): %s", result.returncode, error_msg)
            print(f"Error restoring backup: {error_msg}", file=sys.stderr)
            raise subprocess.CalledProcessError(
                result.returncode, psql_cmd, stderr=result.stderr
            )

        logger.info("Database restored successfully from: %s", backup_path)
        print(f"Database restored successfully from: {backup_path}")

    except subprocess.CalledProcessError as e:
        if e.stderr:
            error_msg = e.stderr.decode()
            logger.error("psql failed: %s", error_msg)
            print(f"Error restoring backup: {error_msg}", file=sys.stderr)
        raise


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Restore PostgreSQL database from backup")
    parser.add_argument(
        "backup_file",
        nargs="?",
        default=None,
        help="Path to backup file (.sql or .sql.gz), or S3 key when using --from-s3",
    )
    parser.add_argument(
        "--from-s3",
        action="store_true",
        dest="from_s3",
        help="Restore from S3: backup_file is the object key (e.g. backups/ugc_backup_20240206_020000.sql.gz)",
    )
    parser.add_argument(
        "--list-s3",
        action="store_true",
        dest="list_s3",
        help="List available backups in S3 and exit (requires S3_* env vars)",
    )
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
        "--confirm",
        action="store_true",
        help="Skip confirmation prompt (use with caution!)",
    )

    args = parser.parse_args()

    if args.list_s3:
        s3_config = _get_s3_config_restore()
        if not s3_config:
            print(
                "Error: S3 credentials required. Set S3_ACCESS_KEY_ID and S3_SECRET_ACCESS_KEY.",
                file=sys.stderr,
            )
            sys.exit(1)
        try:
            keys = list_s3_backups(s3_config)
            if not keys:
                print("No backups found in S3.")
                sys.exit(0)
            print("Available backups in S3 (newest first):")
            for k in keys:
                print(f"  {k}")
            sys.exit(0)
        except Exception as e:
            print(f"Error listing S3: {e}", file=sys.stderr)
            sys.exit(1)

    if not args.backup_file:
        parser.error("backup_file is required (or use --list-s3 to list S3 backups)")

    if args.from_s3:
        s3_config = _get_s3_config_restore()
        if not s3_config:
            print(
                "Error: S3 credentials required for --from-s3. "
                "Set S3_ACCESS_KEY_ID and S3_SECRET_ACCESS_KEY.",
                file=sys.stderr,
            )
            sys.exit(1)
        s3_key = args.backup_file if isinstance(args.backup_file, str) else str(args.backup_file)
        try:
            backup_path = download_backup_from_s3(s3_config, s3_key)
        except FileNotFoundError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"Error downloading from S3: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        backup_path = Path(args.backup_file)
        if not backup_path.exists():
            print(f"Error: Backup file not found: {backup_path}", file=sys.stderr)
            sys.exit(1)

    if not args.password:
        print("Error: Database password is required", file=sys.stderr)
        sys.exit(1)

    if not args.confirm:
        response = input(
            f"WARNING: This will overwrite database '{args.database}'. "
            "Are you sure? (yes/no): "
        )
        if response.lower() != "yes":
            print("Restore cancelled.")
            if args.from_s3 and backup_path.exists():
                backup_path.unlink(missing_ok=True)
            sys.exit(0)

    try:
        logger.info(
            "Starting restore: host=%s port=%s database=%s",
            args.host,
            args.port,
            args.database,
        )
        restore_backup(
            host=args.host,
            port=args.port,
            database=args.database,
            user=args.user,
            password=args.password,
            backup_path=backup_path,
        )
        sys.exit(0)

    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError:
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        if args.from_s3 and backup_path.exists():
            backup_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
