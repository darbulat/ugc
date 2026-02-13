"""Unit tests for restore_db script (S3 restore, list, config)."""

from unittest.mock import MagicMock, patch

import pytest

from scripts.restore_db import (
    _get_s3_config_restore,
    _strip_unsupported_set_commands,
    download_backup_from_s3,
    list_s3_backups,
)


def test_strip_unsupported_set_commands_removes_transaction_timeout() -> None:
    """_strip_unsupported_set_commands removes SET transaction_timeout for PG16."""
    sql = """-- header
SET transaction_timeout = '0';
SELECT 1;
SET transaction_timeout = 0;
"""
    out = _strip_unsupported_set_commands(sql)
    assert "transaction_timeout" not in out
    assert "SELECT 1;" in out


def test_strip_unsupported_set_commands_leaves_other_set_unchanged() -> None:
    """_strip_unsupported_set_commands does not remove other SET commands."""
    sql = "SET client_encoding = 'UTF8';\nSET transaction_timeout = '0';\n"
    out = _strip_unsupported_set_commands(sql)
    assert "client_encoding" in out
    assert "transaction_timeout" not in out


def test_get_s3_config_restore_returns_none_when_keys_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_get_s3_config_restore returns None when key or secret is missing."""
    monkeypatch.delenv("S3_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("S3_SECRET_ACCESS_KEY", raising=False)
    assert _get_s3_config_restore() is None

    monkeypatch.setenv("S3_ACCESS_KEY_ID", "key")
    assert _get_s3_config_restore() is None

    monkeypatch.setenv("S3_SECRET_ACCESS_KEY", "secret")
    config = _get_s3_config_restore()
    assert config is not None
    assert config["access_key"] == "key"
    assert config["secret_key"] == "secret"


def test_get_s3_config_restore_returns_dict_when_keys_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_get_s3_config_restore returns dict with endpoint, bucket, keys."""
    monkeypatch.setenv("S3_ACCESS_KEY_ID", "ak")
    monkeypatch.setenv("S3_SECRET_ACCESS_KEY", "sk")
    monkeypatch.setenv("S3_ENDPOINT_URL", "https://custom.s3.example.com")
    monkeypatch.setenv("S3_BUCKET", "my-bucket")

    config = _get_s3_config_restore()

    assert config is not None
    assert config["endpoint_url"] == "https://custom.s3.example.com"
    assert config["bucket"] == "my-bucket"
    assert config["access_key"] == "ak"
    assert config["secret_key"] == "sk"


def test_get_s3_config_restore_default_endpoint_and_bucket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_get_s3_config_restore uses default Beget endpoint and bucket."""
    monkeypatch.setenv("S3_ACCESS_KEY_ID", "ak")
    monkeypatch.setenv("S3_SECRET_ACCESS_KEY", "sk")
    monkeypatch.delenv("S3_ENDPOINT_URL", raising=False)
    monkeypatch.delenv("S3_BUCKET", raising=False)

    config = _get_s3_config_restore()

    assert config is not None
    assert config["endpoint_url"] == "https://s3.ru1.storage.beget.cloud"
    assert config["bucket"] == "97596cccd207-ugc-s3"


def test_list_s3_backups_returns_keys_newest_first() -> None:
    """list_s3_backups returns backup keys sorted by LastModified descending."""
    from datetime import datetime, timezone

    s3_config = {
        "endpoint_url": "https://s3.example.com",
        "bucket": "b",
        "access_key": "ak",
        "secret_key": "sk",
    }
    older = datetime(2024, 2, 5, 10, 0, 0, tzinfo=timezone.utc)
    newer = datetime(2024, 2, 6, 12, 0, 0, tzinfo=timezone.utc)
    mock_paginate = MagicMock(
        return_value=[
            {
                "Contents": [
                    {
                        "Key": "backups/ugc_backup_20240205_100000.sql.gz",
                        "LastModified": older,
                    },
                    {
                        "Key": "backups/ugc_backup_20240206_120000.sql.gz",
                        "LastModified": newer,
                    },
                ]
            }
        ]
    )
    mock_paginator = MagicMock()
    mock_paginator.paginate = mock_paginate
    mock_client = MagicMock()
    mock_client.get_paginator.return_value = mock_paginator

    with patch(
        "scripts.restore_db._create_s3_client", return_value=mock_client
    ):
        result = list_s3_backups(s3_config)

    assert result == [
        "backups/ugc_backup_20240206_120000.sql.gz",
        "backups/ugc_backup_20240205_100000.sql.gz",
    ]


def test_list_s3_backups_filters_non_backup_keys() -> None:
    """list_s3_backups only includes .sql and .sql.gz keys."""
    s3_config = {
        "endpoint_url": "https://s3.example.com",
        "bucket": "b",
        "access_key": "ak",
        "secret_key": "sk",
    }
    mock_paginate = MagicMock(
        return_value=[
            {
                "Contents": [
                    {
                        "Key": "backups/ugc_backup_20240206.sql.gz",
                        "LastModified": None,
                    },
                    {"Key": "backups/other.txt", "LastModified": None},
                ]
            }
        ]
    )
    mock_paginator = MagicMock()
    mock_paginator.paginate = mock_paginate
    mock_client = MagicMock()
    mock_client.get_paginator.return_value = mock_paginator

    with patch(
        "scripts.restore_db._create_s3_client", return_value=mock_client
    ):
        result = list_s3_backups(s3_config)

    assert result == ["backups/ugc_backup_20240206.sql.gz"]


def test_download_backup_from_s3_adds_backups_prefix() -> None:
    """download_backup_from_s3 adds backups/ prefix when key has no prefix."""
    s3_config = {
        "endpoint_url": "https://s3.example.com",
        "bucket": "b",
        "access_key": "ak",
        "secret_key": "sk",
    }
    mock_body = MagicMock()
    mock_body.read.return_value = b"sql content"
    mock_client = MagicMock()
    mock_client.get_object.return_value = {"Body": mock_body}

    with patch(
        "scripts.restore_db._create_s3_client", return_value=mock_client
    ):
        path = download_backup_from_s3(s3_config, "ugc_backup_20240206.sql.gz")

    try:
        mock_client.get_object.assert_called_once_with(
            Bucket="b", Key="backups/ugc_backup_20240206.sql.gz"
        )
        assert path.suffix == ".gz"
        assert path.read_bytes() == b"sql content"
    finally:
        path.unlink(missing_ok=True)


def test_download_backup_from_s3_keeps_full_key() -> None:
    """download_backup_from_s3 uses key as-is when it starts with backups/."""
    s3_config = {
        "endpoint_url": "https://s3.example.com",
        "bucket": "b",
        "access_key": "ak",
        "secret_key": "sk",
    }
    mock_body = MagicMock()
    mock_body.read.return_value = b"sql content"
    mock_client = MagicMock()
    mock_client.get_object.return_value = {"Body": mock_body}

    with patch(
        "scripts.restore_db._create_s3_client", return_value=mock_client
    ):
        path = download_backup_from_s3(
            s3_config, "backups/ugc_backup_20240206.sql.gz"
        )

    try:
        mock_client.get_object.assert_called_once_with(
            Bucket="b", Key="backups/ugc_backup_20240206.sql.gz"
        )
        assert path.read_bytes() == b"sql content"
    finally:
        path.unlink(missing_ok=True)


def test_download_backup_from_s3_raises_file_not_found_on_no_such_key() -> None:
    """download_backup_from_s3 raises FileNotFoundError on S3 NoSuchKey."""
    from botocore.exceptions import ClientError

    s3_config = {
        "endpoint_url": "https://s3.example.com",
        "bucket": "b",
        "access_key": "ak",
        "secret_key": "sk",
    }
    mock_client = MagicMock()
    mock_client.get_object.side_effect = ClientError(
        {"Error": {"Code": "NoSuchKey", "Message": "Not found"}}, "GetObject"
    )

    with (
        patch("scripts.restore_db._create_s3_client", return_value=mock_client),
        pytest.raises(FileNotFoundError) as exc_info,
    ):
        download_backup_from_s3(s3_config, "backups/missing.sql.gz")

    assert "s3://b/backups/missing.sql.gz" in str(exc_info.value)


def test_download_backup_from_s3_reraises_other_client_errors() -> None:
    """download_backup_from_s3 reraises ClientError when code != NoSuchKey."""
    from botocore.exceptions import ClientError

    s3_config = {
        "endpoint_url": "https://s3.example.com",
        "bucket": "b",
        "access_key": "ak",
        "secret_key": "sk",
    }
    mock_client = MagicMock()
    mock_client.get_object.side_effect = ClientError(
        {"Error": {"Code": "AccessDenied", "Message": "Denied"}}, "GetObject"
    )

    with (
        patch("scripts.restore_db._create_s3_client", return_value=mock_client),
        pytest.raises(ClientError),
    ):
        download_backup_from_s3(s3_config, "backups/ugc_backup.sql.gz")
