"""S3 media storage for blogger photos.

Reuses the same Beget S3-compatible bucket as backups, under a separate
``media/`` prefix. Configuration via environment variables (same names as
``scripts/backup_db.py``):

- ``S3_ENDPOINT_URL`` (default: Beget endpoint)
- ``S3_BUCKET`` (default: backup bucket)
- ``S3_ACCESS_KEY_ID``
- ``S3_SECRET_ACCESS_KEY``
- ``S3_PUBLIC_URL_TEMPLATE`` (optional override; default uses
  ``{endpoint}/{bucket}/{key}``)
"""

from __future__ import annotations

import logging
import mimetypes
import os
import uuid
from dataclasses import dataclass
from typing import Final

logger = logging.getLogger(__name__)

ALLOWED_IMAGE_TYPES: Final = {"image/jpeg", "image/png", "image/webp"}
MAX_IMAGE_BYTES: Final = 10 * 1024 * 1024  # 10 MB


class MediaStorageError(Exception):
    """Raised when media upload fails."""


@dataclass(slots=True)
class S3Config:
    """Resolved S3 configuration for media uploads."""

    endpoint_url: str
    bucket: str
    access_key: str
    secret_key: str
    public_url_template: str

    @classmethod
    def from_env(cls) -> "S3Config":
        """Load S3 config from env; raise if mandatory keys missing."""
        endpoint = os.getenv(
            "S3_ENDPOINT_URL", "https://s3.ru1.storage.beget.cloud"
        )
        bucket = os.getenv("S3_BUCKET", "97596cccd207-ugc-s3")
        access_key = os.getenv("S3_ACCESS_KEY_ID", "").strip()
        secret_key = os.getenv("S3_SECRET_ACCESS_KEY", "").strip()
        if not access_key or not secret_key:
            raise MediaStorageError(
                "S3_ACCESS_KEY_ID / S3_SECRET_ACCESS_KEY not configured"
            )
        public_template = os.getenv(
            "S3_PUBLIC_URL_TEMPLATE",
            "{endpoint}/{bucket}/{key}",
        )
        return cls(
            endpoint_url=endpoint,
            bucket=bucket,
            access_key=access_key,
            secret_key=secret_key,
            public_url_template=public_template,
        )


def upload_image_to_s3(
    data: bytes,
    content_type: str,
    *,
    prefix: str = "media/blogger-photos",
    config: S3Config | None = None,
) -> str:
    """Upload an image to S3 and return its public URL.

    Validates content type and size; assigns a random key under ``prefix``.
    """
    if content_type not in ALLOWED_IMAGE_TYPES:
        raise MediaStorageError(
            f"Unsupported image type: {content_type}. "
            f"Allowed: {sorted(ALLOWED_IMAGE_TYPES)}"
        )
    if len(data) > MAX_IMAGE_BYTES:
        raise MediaStorageError(
            f"Image too large: {len(data)} bytes (max {MAX_IMAGE_BYTES})"
        )

    cfg = config or S3Config.from_env()

    extension = mimetypes.guess_extension(content_type, strict=False) or ".bin"
    if extension == ".jpe":
        extension = ".jpg"
    key = f"{prefix.strip('/')}/{uuid.uuid4().hex}{extension}"

    import boto3  # type: ignore[import-untyped]  # noqa: PLC0415
    from botocore.config import (  # type: ignore[import-untyped]  # noqa: PLC0415
        Config as BotoConfig,
    )

    client = boto3.client(
        "s3",
        endpoint_url=cfg.endpoint_url,
        aws_access_key_id=cfg.access_key,
        aws_secret_access_key=cfg.secret_key,
        config=BotoConfig(s3={"addressing_style": "path"}),
    )
    client.put_object(
        Bucket=cfg.bucket,
        Key=key,
        Body=data,
        ContentType=content_type,
        ACL="public-read",
    )
    public_url = cfg.public_url_template.format(
        endpoint=cfg.endpoint_url.rstrip("/"),
        bucket=cfg.bucket,
        key=key,
    )
    logger.info(
        "uploaded media to s3",
        extra={"event": "s3_media_upload", "key": key, "size": len(data)},
    )
    return public_url
