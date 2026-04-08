"""Unit tests for ``ugc_bot.infrastructure.s3_storage``."""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest

from ugc_bot.infrastructure.s3_storage import (
    MAX_IMAGE_BYTES,
    MediaStorageError,
    S3Config,
    upload_image_to_s3,
)


def _install_fake_boto3(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Install fake boto3 / botocore.config modules; return fake client."""
    fake_client = MagicMock()
    fake_boto3 = types.ModuleType("boto3")
    fake_boto3.client = MagicMock(return_value=fake_client)  # type: ignore[attr-defined]
    fake_botocore = types.ModuleType("botocore")
    fake_botocore_config = types.ModuleType("botocore.config")
    fake_botocore_config.Config = MagicMock(return_value=object())  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)
    monkeypatch.setitem(sys.modules, "botocore", fake_botocore)
    monkeypatch.setitem(sys.modules, "botocore.config", fake_botocore_config)
    return fake_client


def test_s3config_from_env_uses_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``from_env`` reads access keys and falls back to Beget defaults."""
    monkeypatch.setenv("S3_ACCESS_KEY_ID", "ak")
    monkeypatch.setenv("S3_SECRET_ACCESS_KEY", "sk")
    monkeypatch.delenv("S3_ENDPOINT_URL", raising=False)
    monkeypatch.delenv("S3_BUCKET", raising=False)
    monkeypatch.delenv("S3_PUBLIC_URL_TEMPLATE", raising=False)
    cfg = S3Config.from_env()
    assert cfg.access_key == "ak"
    assert cfg.secret_key == "sk"
    assert "beget" in cfg.endpoint_url
    assert cfg.bucket
    assert "{key}" in cfg.public_url_template


def test_s3config_from_env_missing_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``from_env`` raises when access keys are absent."""
    monkeypatch.delenv("S3_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("S3_SECRET_ACCESS_KEY", raising=False)
    with pytest.raises(MediaStorageError):
        S3Config.from_env()


def test_upload_image_rejects_unsupported_type() -> None:
    """Non-image content types are rejected."""
    cfg = S3Config(
        endpoint_url="https://s3.example.com",
        bucket="bkt",
        access_key="ak",
        secret_key="sk",
        public_url_template="{endpoint}/{bucket}/{key}",
    )
    with pytest.raises(MediaStorageError):
        upload_image_to_s3(b"data", "application/pdf", config=cfg)


def test_upload_image_rejects_oversized_payload() -> None:
    """Files larger than ``MAX_IMAGE_BYTES`` are rejected."""
    cfg = S3Config(
        endpoint_url="https://s3.example.com",
        bucket="bkt",
        access_key="ak",
        secret_key="sk",
        public_url_template="{endpoint}/{bucket}/{key}",
    )
    with pytest.raises(MediaStorageError):
        upload_image_to_s3(
            b"x" * (MAX_IMAGE_BYTES + 1), "image/png", config=cfg
        )


def test_upload_image_uploads_and_returns_public_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Successful upload calls ``put_object`` and formats the public URL."""
    fake_client = _install_fake_boto3(monkeypatch)
    cfg = S3Config(
        endpoint_url="https://s3.example.com/",
        bucket="bkt",
        access_key="ak",
        secret_key="sk",
        public_url_template="{endpoint}/{bucket}/{key}",
    )
    url = upload_image_to_s3(b"\x89PNGdata", "image/png", config=cfg)
    fake_client.put_object.assert_called_once()
    kwargs = fake_client.put_object.call_args.kwargs
    assert kwargs["Bucket"] == "bkt"
    assert kwargs["ContentType"] == "image/png"
    assert kwargs["ACL"] == "public-read"
    assert kwargs["Key"].startswith("media/blogger-photos/")
    assert kwargs["Key"].endswith(".png")
    assert url.startswith("https://s3.example.com/bkt/media/blogger-photos/")


def test_upload_image_uses_env_config_when_none_passed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``config`` is None, ``S3Config.from_env`` is used."""
    fake_client = _install_fake_boto3(monkeypatch)
    monkeypatch.setenv("S3_ACCESS_KEY_ID", "ak")
    monkeypatch.setenv("S3_SECRET_ACCESS_KEY", "sk")
    monkeypatch.setenv("S3_ENDPOINT_URL", "https://s3.example.com")
    monkeypatch.setenv("S3_BUCKET", "bkt")
    monkeypatch.delenv("S3_PUBLIC_URL_TEMPLATE", raising=False)
    url = upload_image_to_s3(b"data", "image/jpeg")
    assert "bkt" in url
    fake_client.put_object.assert_called_once()
    kwargs = fake_client.put_object.call_args.kwargs
    assert kwargs["Key"].endswith(".jpg")


def test_upload_image_webp_extension(monkeypatch: pytest.MonkeyPatch) -> None:
    """WebP content type maps to a ``.webp`` key."""
    fake_client = _install_fake_boto3(monkeypatch)
    cfg = S3Config(
        endpoint_url="https://s3.example.com",
        bucket="bkt",
        access_key="ak",
        secret_key="sk",
        public_url_template="{endpoint}/{bucket}/{key}",
    )
    upload_image_to_s3(b"data", "image/webp", config=cfg)
    kwargs = fake_client.put_object.call_args.kwargs
    assert kwargs["Key"].endswith(".webp")
