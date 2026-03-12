"""Unit tests for backup_db script (S3 upload and config)."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import boto3  # noqa: F401 - ensure module loaded so patch("boto3.client") works
import pytest

from scripts.backup_db import (
    _get_s3_config,
    _parse_database_url,
    cleanup_old_s3_backups,
    upload_backup_to_s3,
)


def test_parse_database_url_returns_none_for_empty_or_non_postgres() -> None:
    """_parse_database_url returns None for empty or non-PostgreSQL URL."""
    assert _parse_database_url("") is None
    assert _parse_database_url("sqlite:///file.db") is None
    assert _parse_database_url("mysql://user:pass@host/db") is None


def test_parse_database_url_parses_postgresql_url() -> None:
    """_parse_database_url extracts host, port, database, user, password."""
    url = "postgresql://ugc:secret@db:5432/ugc"
    got = _parse_database_url(url)
    assert got is not None
    assert got["host"] == "db"
    assert got["port"] == 5432
    assert got["database"] == "ugc"
    assert got["user"] == "ugc"
    assert got["password"] == "secret"


def test_parse_database_url_parses_postgresql_psycopg_url() -> None:
    """_parse_database_url accepts postgresql+psycopg scheme."""
    url = "postgresql+psycopg://u:p@localhost:5433/mydb"
    got = _parse_database_url(url)
    assert got is not None
    assert got["host"] == "localhost"
    assert got["port"] == 5433
    assert got["database"] == "mydb"
    assert got["user"] == "u"
    assert got["password"] == "p"


def test_parse_database_url_defaults_port_and_database() -> None:
    """_parse_database_url uses 5432 and ugc when port/path missing."""
    got = _parse_database_url("postgresql://u:p@host/")
    assert got is not None
    assert got["port"] == 5432
    assert got["database"] == "ugc"


def test_get_s3_config_returns_none_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_get_s3_config returns None when S3_BACKUP_ENABLED is unset or false."""
    monkeypatch.delenv("S3_BACKUP_ENABLED", raising=False)
    monkeypatch.setenv("S3_ACCESS_KEY_ID", "key")
    monkeypatch.setenv("S3_SECRET_ACCESS_KEY", "secret")
    assert _get_s3_config() is None

    monkeypatch.setenv("S3_BACKUP_ENABLED", "false")
    assert _get_s3_config() is None

    monkeypatch.setenv("S3_BACKUP_ENABLED", "0")
    assert _get_s3_config() is None


def test_get_s3_config_returns_none_when_keys_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_get_s3_config returns None when access key or secret is missing."""
    monkeypatch.setenv("S3_BACKUP_ENABLED", "true")
    monkeypatch.delenv("S3_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("S3_SECRET_ACCESS_KEY", raising=False)
    assert _get_s3_config() is None

    monkeypatch.setenv("S3_ACCESS_KEY_ID", "key")
    assert _get_s3_config() is None

    monkeypatch.setenv("S3_SECRET_ACCESS_KEY", "secret")
    config = _get_s3_config()
    assert config is not None
    assert config["access_key"] == "key"
    assert config["secret_key"] == "secret"


def test_get_s3_config_returns_dict_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_get_s3_config returns dict with endpoint, bucket, keys when all set."""
    monkeypatch.setenv("S3_BACKUP_ENABLED", "true")
    monkeypatch.setenv("S3_ACCESS_KEY_ID", "ak")
    monkeypatch.setenv("S3_SECRET_ACCESS_KEY", "sk")
    monkeypatch.setenv("S3_ENDPOINT_URL", "https://custom.s3.example.com")
    monkeypatch.setenv("S3_BUCKET", "my-bucket")

    config = _get_s3_config()
    assert config is not None
    assert config["endpoint_url"] == "https://custom.s3.example.com"
    assert config["bucket"] == "my-bucket"
    assert config["access_key"] == "ak"
    assert config["secret_key"] == "sk"


def test_get_s3_config_default_endpoint_and_bucket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_get_s3_config uses default Beget endpoint and bucket when not set."""
    monkeypatch.setenv("S3_BACKUP_ENABLED", "1")
    monkeypatch.setenv("S3_ACCESS_KEY_ID", "ak")
    monkeypatch.setenv("S3_SECRET_ACCESS_KEY", "sk")
    monkeypatch.delenv("S3_ENDPOINT_URL", raising=False)
    monkeypatch.delenv("S3_BUCKET", raising=False)

    config = _get_s3_config()
    assert config is not None
    assert config["endpoint_url"] == "https://s3.ru1.storage.beget.cloud"
    assert config["bucket"] == "97596cccd207-ugc-s3"


def test_upload_backup_to_s3_calls_client_with_path_style(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """upload_backup_to_s3 uses path-style boto3 client and upload_file."""
    (tmp_path / "ugc_backup_20240206_120000.sql.gz").write_bytes(b"x")
    backup_path = tmp_path / "ugc_backup_20240206_120000.sql.gz"
    s3_config = {
        "endpoint_url": "https://s3.example.com",
        "bucket": "bkt",
        "access_key": "ak",
        "secret_key": "sk",
    }

    mock_client = MagicMock()
    mock_boto3_client = MagicMock(return_value=mock_client)

    with patch("boto3.client", mock_boto3_client):
        result = upload_backup_to_s3(backup_path, s3_config)

    assert result is True
    mock_boto3_client.assert_called_once()
    call_kw = mock_boto3_client.call_args[1]
    assert call_kw["endpoint_url"] == "https://s3.example.com"
    assert call_kw["aws_access_key_id"] == "ak"
    assert call_kw["aws_secret_access_key"] == "sk"
    mock_client.upload_file.assert_called_once_with(
        Filename=str(backup_path),
        Bucket="bkt",
        Key="backups/ugc_backup_20240206_120000.sql.gz",
    )


def test_upload_backup_to_s3_returns_false_on_exception(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """upload_backup_to_s3 returns False on upload failure, does not raise."""
    (tmp_path / "ugc_backup_20240206_120000.sql.gz").write_bytes(b"x")
    backup_path = tmp_path / "ugc_backup_20240206_120000.sql.gz"
    s3_config = {
        "endpoint_url": "https://s3.example.com",
        "bucket": "bkt",
        "access_key": "ak",
        "secret_key": "sk",
    }

    mock_client = MagicMock()
    mock_client.upload_file.side_effect = OSError("network error")

    with patch("boto3.client", return_value=mock_client):
        result = upload_backup_to_s3(backup_path, s3_config)

    assert result is False


def test_cleanup_old_s3_backups_deletes_old_objects() -> None:
    """cleanup_old_s3_backups deletes objects older than keep_days."""
    s3_config = {
        "endpoint_url": "https://s3.example.com",
        "bucket": "bkt",
        "access_key": "ak",
        "secret_key": "sk",
    }

    from datetime import datetime, timezone

    old_date = datetime(2020, 1, 1, tzinfo=timezone.utc)
    paginate_result = {
        "Contents": [
            {
                "Key": "backups/ugc_backup_20200101_000000.sql.gz",
                "LastModified": old_date,
            },
        ],
    }

    mock_paginator = MagicMock()
    mock_paginator.paginate.return_value = [paginate_result]
    mock_client = MagicMock()
    mock_client.get_paginator.return_value = mock_paginator

    with (
        patch("boto3.client", return_value=mock_client),
        patch(
            "scripts.backup_db.datetime",
        ) as mock_dt,
    ):
        mock_dt.now.return_value.timestamp.return_value = 1700000000.0  # 2023
        cleanup_old_s3_backups(s3_config, prefix="backups/", keep_days=7)

    mock_client.delete_objects.assert_called_once()
    call_kw = mock_client.delete_objects.call_args[1]
    assert call_kw["Bucket"] == "bkt"
    assert len(call_kw["Delete"]["Objects"]) == 1
    assert (
        call_kw["Delete"]["Objects"][0]["Key"]
        == "backups/ugc_backup_20200101_000000.sql.gz"
    )


def test_cleanup_old_s3_backups_handles_empty_listing() -> None:
    """cleanup_old_s3_backups skips delete_objects when no old objects."""
    s3_config = {
        "endpoint_url": "https://s3.example.com",
        "bucket": "bkt",
        "access_key": "ak",
        "secret_key": "sk",
    }

    mock_paginator = MagicMock()
    mock_paginator.paginate.return_value = [{"Contents": []}]
    mock_client = MagicMock()
    mock_client.get_paginator.return_value = mock_paginator

    with patch("boto3.client", return_value=mock_client):
        cleanup_old_s3_backups(s3_config, prefix="backups/", keep_days=7)

    mock_client.delete_objects.assert_not_called()
