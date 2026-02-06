#!/usr/bin/env python3
"""Script for restoring PostgreSQL database from backup."""

import argparse
import gzip
import os
import subprocess
import sys
from pathlib import Path


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
    ]

    try:
        if backup_path.suffix == ".gz" or backup_path.name.endswith(".sql.gz"):
            # Decompress and restore
            with gzip.open(backup_path, "rt") as f:
                result = subprocess.run(
                    psql_cmd,
                    stdin=f,
                    stderr=subprocess.PIPE,
                    env=env,
                    check=True,
                )
        else:
            # Restore directly
            with open(backup_path, "r") as f:
                result = subprocess.run(
                    psql_cmd,
                    stdin=f,
                    stderr=subprocess.PIPE,
                    env=env,
                    check=True,
                )

        print(f"Database restored successfully from: {backup_path}")

    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.decode() if e.stderr else str(e)
        print(f"Error restoring backup: {error_msg}", file=sys.stderr)
        raise


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Restore PostgreSQL database from backup")
    parser.add_argument(
        "backup_file",
        type=Path,
        help="Path to backup file (.sql or .sql.gz)",
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
            sys.exit(0)

    try:
        restore_backup(
            host=args.host,
            port=args.port,
            database=args.database,
            user=args.user,
            password=args.password,
            backup_path=args.backup_file,
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


if __name__ == "__main__":
    main()
