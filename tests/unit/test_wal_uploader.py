"""Unit tests for wal_uploader script."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.wal_uploader import (
    _get_s3_config,
    cleanup_old_wal_s3,
    upload_wal_files,
)


def test_get_s3_config_returns_none_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_get_s3_config returns None when S3_BACKUP_ENABLED is not set."""
    monkeypatch.delenv("S3_BACKUP_ENABLED", raising=False)
    assert _get_s3_config() is None


def test_get_s3_config_returns_none_when_keys_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_get_s3_config returns None when access key or secret is missing."""
    monkeypatch.setenv("S3_BACKUP_ENABLED", "true")
    monkeypatch.delenv("S3_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("S3_SECRET_ACCESS_KEY", raising=False)
    assert _get_s3_config() is None


def test_get_s3_config_returns_dict_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_get_s3_config returns full config when enabled with keys."""
    monkeypatch.setenv("S3_BACKUP_ENABLED", "true")
    monkeypatch.setenv("S3_ACCESS_KEY_ID", "ak")
    monkeypatch.setenv("S3_SECRET_ACCESS_KEY", "sk")
    config = _get_s3_config()
    assert config is not None
    assert config["access_key"] == "ak"
    assert config["secret_key"] == "sk"


def test_upload_wal_files_uploads_and_removes(tmp_path: Path) -> None:
    """upload_wal_files uploads files and removes them after success."""
    (tmp_path / "000000010000000000000001").write_bytes(b"waldata1")
    (tmp_path / "000000010000000000000002").write_bytes(b"waldata2")

    s3_config = {
        "endpoint_url": "https://s3.example.com",
        "bucket": "bkt",
        "access_key": "ak",
        "secret_key": "sk",
    }
    mock_client = MagicMock()

    with patch(
        "scripts.wal_uploader._create_s3_client", return_value=mock_client
    ):
        result = upload_wal_files(tmp_path, s3_config, remove_after_upload=True)

    assert result == 2
    assert mock_client.put_object.call_count == 2
    # Local files should be removed
    assert not (tmp_path / "000000010000000000000001").exists()
    assert not (tmp_path / "000000010000000000000002").exists()


def test_upload_wal_files_skips_partial_files(tmp_path: Path) -> None:
    """upload_wal_files skips .partial files."""
    (tmp_path / "000000010000000000000001").write_bytes(b"waldata")
    (tmp_path / "000000010000000000000002.partial").write_bytes(b"partial")

    s3_config = {
        "endpoint_url": "https://s3.example.com",
        "bucket": "bkt",
        "access_key": "ak",
        "secret_key": "sk",
    }
    mock_client = MagicMock()

    with patch(
        "scripts.wal_uploader._create_s3_client", return_value=mock_client
    ):
        result = upload_wal_files(tmp_path, s3_config)

    assert result == 1
    # Partial file should still exist
    assert (tmp_path / "000000010000000000000002.partial").exists()


def test_upload_wal_files_keeps_files_when_remove_disabled(
    tmp_path: Path,
) -> None:
    """upload_wal_files keeps local files when remove_after_upload=False."""
    (tmp_path / "000000010000000000000001").write_bytes(b"waldata")

    s3_config = {
        "endpoint_url": "https://s3.example.com",
        "bucket": "bkt",
        "access_key": "ak",
        "secret_key": "sk",
    }
    mock_client = MagicMock()

    with patch(
        "scripts.wal_uploader._create_s3_client", return_value=mock_client
    ):
        result = upload_wal_files(
            tmp_path, s3_config, remove_after_upload=False
        )

    assert result == 1
    assert (tmp_path / "000000010000000000000001").exists()


def test_upload_wal_files_returns_zero_for_empty_dir(tmp_path: Path) -> None:
    """upload_wal_files returns 0 when directory is empty."""
    s3_config = {
        "endpoint_url": "https://s3.example.com",
        "bucket": "bkt",
        "access_key": "ak",
        "secret_key": "sk",
    }
    mock_client = MagicMock()

    with patch(
        "scripts.wal_uploader._create_s3_client", return_value=mock_client
    ):
        result = upload_wal_files(tmp_path, s3_config)

    assert result == 0
    mock_client.put_object.assert_not_called()


def test_upload_wal_files_returns_zero_for_nonexistent_dir() -> None:
    """upload_wal_files returns 0 when directory does not exist."""
    s3_config = {
        "endpoint_url": "https://s3.example.com",
        "bucket": "bkt",
        "access_key": "ak",
        "secret_key": "sk",
    }
    result = upload_wal_files(Path("/nonexistent_dir"), s3_config)
    assert result == 0


def test_upload_wal_files_continues_on_upload_error(tmp_path: Path) -> None:
    """upload_wal_files continues uploading after a single file fails."""
    (tmp_path / "000000010000000000000001").write_bytes(b"waldata1")
    (tmp_path / "000000010000000000000002").write_bytes(b"waldata2")

    s3_config = {
        "endpoint_url": "https://s3.example.com",
        "bucket": "bkt",
        "access_key": "ak",
        "secret_key": "sk",
    }
    mock_client = MagicMock()
    # First upload fails, second succeeds
    mock_client.put_object.side_effect = [OSError("network error"), None]

    with patch(
        "scripts.wal_uploader._create_s3_client", return_value=mock_client
    ):
        result = upload_wal_files(tmp_path, s3_config)

    assert result == 1
    # Failed file should still exist
    assert (tmp_path / "000000010000000000000001").exists()
    # Successful file should be removed
    assert not (tmp_path / "000000010000000000000002").exists()


def test_cleanup_old_wal_s3_deletes_old_objects() -> None:
    """cleanup_old_wal_s3 deletes objects older than keep_days."""
    from datetime import datetime, timezone

    s3_config = {
        "endpoint_url": "https://s3.example.com",
        "bucket": "bkt",
        "access_key": "ak",
        "secret_key": "sk",
    }
    old_date = datetime(2020, 1, 1, tzinfo=timezone.utc)
    paginate_result = {
        "Contents": [
            {
                "Key": "wal_archive/000000010000000000000001",
                "LastModified": old_date,
            },
        ],
    }
    mock_paginator = MagicMock()
    mock_paginator.paginate.return_value = [paginate_result]
    mock_client = MagicMock()
    mock_client.get_paginator.return_value = mock_paginator

    with patch(
        "scripts.wal_uploader._create_s3_client",
        return_value=mock_client,
    ):
        result = cleanup_old_wal_s3(s3_config, keep_days=7)

    assert result == 1
    mock_client.delete_objects.assert_called_once()


def test_cleanup_old_wal_s3_skips_when_no_old_objects() -> None:
    """cleanup_old_wal_s3 does not delete when no old objects."""
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

    with patch(
        "scripts.wal_uploader._create_s3_client", return_value=mock_client
    ):
        result = cleanup_old_wal_s3(s3_config, keep_days=7)

    assert result == 0
    mock_client.delete_objects.assert_not_called()
