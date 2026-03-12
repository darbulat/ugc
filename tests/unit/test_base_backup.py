"""Unit tests for base_backup script."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.base_backup import (
    _get_s3_config,
    cleanup_old_base_backups,
    cleanup_old_base_backups_s3,
    upload_base_backup_to_s3,
)


def test_get_s3_config_returns_none_when_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_get_s3_config returns None when S3 is not enabled."""
    monkeypatch.delenv("S3_BACKUP_ENABLED", raising=False)
    assert _get_s3_config() is None


def test_get_s3_config_returns_none_when_keys_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_get_s3_config returns None when keys are missing."""
    monkeypatch.setenv("S3_BACKUP_ENABLED", "true")
    monkeypatch.delenv("S3_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("S3_SECRET_ACCESS_KEY", raising=False)
    assert _get_s3_config() is None


def test_get_s3_config_returns_dict_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_get_s3_config returns config dict when enabled with keys."""
    monkeypatch.setenv("S3_BACKUP_ENABLED", "true")
    monkeypatch.setenv("S3_ACCESS_KEY_ID", "ak")
    monkeypatch.setenv("S3_SECRET_ACCESS_KEY", "sk")
    config = _get_s3_config()
    assert config is not None
    assert config["access_key"] == "ak"
    assert config["secret_key"] == "sk"


def test_cleanup_old_base_backups_removes_old_files(tmp_path: Path) -> None:
    """cleanup_old_base_backups removes files older than keep_days."""
    import os

    old_file = tmp_path / "ugc_basebackup_20200101_000000.tar.gz"
    old_file.write_bytes(b"old")
    # Set mtime to a very old time
    os.utime(old_file, (0, 0))

    new_file = tmp_path / "ugc_basebackup_20990101_000000.tar.gz"
    new_file.write_bytes(b"new")

    cleanup_old_base_backups(tmp_path, keep_days=1)

    assert not old_file.exists()
    assert new_file.exists()


def test_cleanup_old_base_backups_handles_empty_dir(tmp_path: Path) -> None:
    """cleanup_old_base_backups does nothing for empty directory."""
    cleanup_old_base_backups(tmp_path, keep_days=7)


def test_cleanup_old_base_backups_handles_nonexistent_dir() -> None:
    """cleanup_old_base_backups does nothing for nonexistent directory."""
    cleanup_old_base_backups(Path("/nonexistent"), keep_days=7)


def test_upload_base_backup_to_s3_uploads_file(tmp_path: Path) -> None:
    """upload_base_backup_to_s3 uploads file with correct key."""
    backup = tmp_path / "ugc_basebackup_20240206_120000.tar.gz"
    backup.write_bytes(b"basedata")

    s3_config = {
        "endpoint_url": "https://s3.example.com",
        "bucket": "bkt",
        "access_key": "ak",
        "secret_key": "sk",
    }
    mock_client = MagicMock()

    with patch(
        "scripts.base_backup._create_s3_client", return_value=mock_client
    ):
        result = upload_base_backup_to_s3(backup, s3_config)

    assert result is True
    mock_client.upload_file.assert_called_once_with(
        Filename=str(backup),
        Bucket="bkt",
        Key="base_backups/ugc_basebackup_20240206_120000.tar.gz",
    )


def test_upload_base_backup_to_s3_returns_false_on_error(
    tmp_path: Path,
) -> None:
    """upload_base_backup_to_s3 returns False on upload failure."""
    backup = tmp_path / "ugc_basebackup_20240206_120000.tar.gz"
    backup.write_bytes(b"data")

    s3_config = {
        "endpoint_url": "https://s3.example.com",
        "bucket": "bkt",
        "access_key": "ak",
        "secret_key": "sk",
    }
    mock_client = MagicMock()
    mock_client.upload_file.side_effect = OSError("network error")

    with patch(
        "scripts.base_backup._create_s3_client", return_value=mock_client
    ):
        result = upload_base_backup_to_s3(backup, s3_config)

    assert result is False


def test_cleanup_old_base_backups_s3_deletes_old_objects() -> None:
    """cleanup_old_base_backups_s3 deletes objects older than keep_days."""
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
                "Key": "base_backups/ugc_basebackup_20200101_000000.tar.gz",
                "LastModified": old_date,
            },
        ],
    }
    mock_paginator = MagicMock()
    mock_paginator.paginate.return_value = [paginate_result]
    mock_client = MagicMock()
    mock_client.get_paginator.return_value = mock_paginator

    with (
        patch(
            "scripts.base_backup._create_s3_client", return_value=mock_client
        ),
        patch("scripts.base_backup.datetime") as mock_dt,
    ):
        mock_dt.now.return_value.timestamp.return_value = 1700000000.0
        cleanup_old_base_backups_s3(s3_config, keep_days=7)

    mock_client.delete_objects.assert_called_once()
    call_kw = mock_client.delete_objects.call_args[1]
    assert len(call_kw["Delete"]["Objects"]) == 1


def test_cleanup_old_base_backups_s3_handles_empty_listing() -> None:
    """cleanup_old_base_backups_s3 skips delete when no old objects."""
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
        "scripts.base_backup._create_s3_client", return_value=mock_client
    ):
        cleanup_old_base_backups_s3(s3_config, keep_days=7)

    mock_client.delete_objects.assert_not_called()
