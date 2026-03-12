"""Unit tests for pitr_restore script."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.pitr_restore import (
    _get_s3_config,
    configure_recovery,
    download_wal_files,
    list_base_backups,
)


def test_get_s3_config_returns_none_when_keys_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_get_s3_config returns None when access key or secret is missing."""
    monkeypatch.delenv("S3_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("S3_SECRET_ACCESS_KEY", raising=False)
    assert _get_s3_config() is None


def test_get_s3_config_returns_dict_when_keys_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_get_s3_config returns config when keys are set."""
    monkeypatch.setenv("S3_ACCESS_KEY_ID", "ak")
    monkeypatch.setenv("S3_SECRET_ACCESS_KEY", "sk")
    config = _get_s3_config()
    assert config is not None
    assert config["access_key"] == "ak"


def test_list_base_backups_returns_newest_first() -> None:
    """list_base_backups returns base backup keys sorted newest first."""
    from datetime import datetime, timezone

    s3_config = {
        "endpoint_url": "https://s3.example.com",
        "bucket": "b",
        "access_key": "ak",
        "secret_key": "sk",
    }
    older = datetime(2024, 2, 5, 10, 0, 0, tzinfo=timezone.utc)
    newer = datetime(2024, 2, 6, 12, 0, 0, tzinfo=timezone.utc)
    key_old = "base_backups/ugc_basebackup_20240205_100000.tar.gz"
    key_new = "base_backups/ugc_basebackup_20240206_120000.tar.gz"
    mock_paginate = MagicMock(
        return_value=[
            {
                "Contents": [
                    {"Key": key_old, "LastModified": older},
                    {"Key": key_new, "LastModified": newer},
                ]
            }
        ]
    )
    mock_paginator = MagicMock()
    mock_paginator.paginate = mock_paginate
    mock_client = MagicMock()
    mock_client.get_paginator.return_value = mock_paginator

    with patch(
        "scripts.pitr_restore._create_s3_client", return_value=mock_client
    ):
        result = list_base_backups(s3_config)

    assert result == [
        "base_backups/ugc_basebackup_20240206_120000.tar.gz",
        "base_backups/ugc_basebackup_20240205_100000.tar.gz",
    ]


def test_list_base_backups_filters_non_tar_gz() -> None:
    """list_base_backups only includes .tar.gz keys."""
    from datetime import datetime, timezone

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
                        "Key": "base_backups/ugc_basebackup_20240206.tar.gz",
                        "LastModified": datetime(
                            2024, 2, 6, tzinfo=timezone.utc
                        ),
                    },
                    {
                        "Key": "base_backups/readme.txt",
                        "LastModified": datetime(
                            2024, 2, 6, tzinfo=timezone.utc
                        ),
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
        "scripts.pitr_restore._create_s3_client", return_value=mock_client
    ):
        result = list_base_backups(s3_config)

    assert result == ["base_backups/ugc_basebackup_20240206.tar.gz"]


def test_download_wal_files_downloads_and_counts() -> None:
    """download_wal_files downloads WAL files from S3."""
    import tempfile

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
                    {"Key": "wal_archive/000000010000000000000001"},
                    {"Key": "wal_archive/000000010000000000000002"},
                ]
            }
        ]
    )
    mock_paginator = MagicMock()
    mock_paginator.paginate = mock_paginate
    mock_client = MagicMock()
    mock_client.get_paginator.return_value = mock_paginator

    with (
        patch(
            "scripts.pitr_restore._create_s3_client", return_value=mock_client
        ),
        tempfile.TemporaryDirectory() as tmpdir,
    ):
        wal_dir = Path(tmpdir) / "wal"
        count = download_wal_files(s3_config, wal_dir)

    assert count == 2
    assert mock_client.download_file.call_count == 2


def test_download_wal_files_skips_existing(tmp_path: Path) -> None:
    """download_wal_files skips files that already exist locally."""
    s3_config = {
        "endpoint_url": "https://s3.example.com",
        "bucket": "b",
        "access_key": "ak",
        "secret_key": "sk",
    }
    wal_dir = tmp_path / "wal"
    wal_dir.mkdir()
    (wal_dir / "000000010000000000000001").write_bytes(b"existing")

    mock_paginate = MagicMock(
        return_value=[
            {
                "Contents": [
                    {"Key": "wal_archive/000000010000000000000001"},
                    {"Key": "wal_archive/000000010000000000000002"},
                ]
            }
        ]
    )
    mock_paginator = MagicMock()
    mock_paginator.paginate = mock_paginate
    mock_client = MagicMock()
    mock_client.get_paginator.return_value = mock_paginator

    with patch(
        "scripts.pitr_restore._create_s3_client", return_value=mock_client
    ):
        count = download_wal_files(s3_config, wal_dir)

    assert count == 1
    assert mock_client.download_file.call_count == 1


def test_configure_recovery_creates_signal_and_config(tmp_path: Path) -> None:
    """configure_recovery creates recovery.signal and configures auto.conf."""
    pgdata = tmp_path / "pgdata"
    pgdata.mkdir()
    wal_dir = tmp_path / "wal"

    configure_recovery(pgdata, wal_dir, target_time="2025-06-01 12:00:00")

    assert (pgdata / "recovery.signal").exists()
    auto_conf = (pgdata / "postgresql.auto.conf").read_text()
    assert f"restore_command = 'cp {wal_dir}/%f %p'" in auto_conf
    assert "recovery_target_time = '2025-06-01 12:00:00'" in auto_conf
    assert "recovery_target_action = 'promote'" in auto_conf


def test_configure_recovery_without_target_time(tmp_path: Path) -> None:
    """configure_recovery works without target_time (recover to latest)."""
    pgdata = tmp_path / "pgdata"
    pgdata.mkdir()
    wal_dir = tmp_path / "wal"

    configure_recovery(pgdata, wal_dir)

    auto_conf = (pgdata / "postgresql.auto.conf").read_text()
    assert "restore_command" in auto_conf
    assert "recovery_target_time" not in auto_conf


def test_configure_recovery_preserves_existing_config(tmp_path: Path) -> None:
    """configure_recovery preserves existing auto.conf settings."""
    pgdata = tmp_path / "pgdata"
    pgdata.mkdir()
    wal_dir = tmp_path / "wal"

    # Write existing config
    auto_conf = pgdata / "postgresql.auto.conf"
    auto_conf.write_text("shared_buffers = '256MB'\n")

    configure_recovery(pgdata, wal_dir, target_time="2025-06-01 12:00:00")

    content = auto_conf.read_text()
    assert "shared_buffers = '256MB'" in content
    assert "restore_command" in content
    assert "recovery_target_time" in content


def test_configure_recovery_replaces_previous_recovery_settings(
    tmp_path: Path,
) -> None:
    """configure_recovery removes old restore_command/recovery_target_time."""
    pgdata = tmp_path / "pgdata"
    pgdata.mkdir()
    wal_dir = tmp_path / "wal"

    auto_conf = pgdata / "postgresql.auto.conf"
    auto_conf.write_text(
        "restore_command = 'old command'\n"
        "recovery_target_time = '2024-01-01 00:00:00'\n"
        "shared_buffers = '256MB'\n"
    )

    configure_recovery(pgdata, wal_dir, target_time="2025-06-01 12:00:00")

    content = auto_conf.read_text()
    assert "old command" not in content
    assert "2024-01-01" not in content
    assert "2025-06-01" in content
    assert "shared_buffers = '256MB'" in content
