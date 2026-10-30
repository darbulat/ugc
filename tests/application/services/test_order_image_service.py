import io
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from PIL import Image

from ugc_bot.application.services.order_image_service import OrderImageService


class Tx:
    @asynccontextmanager
    async def transaction(self):
        yield object()


class Repo:
    def __init__(self):
        self.images = {}

    async def authorize(self, owner, principal, *, session):
        return owner.int != 0

    async def save(self, value, *, session):
        self.images[value.token] = value

    async def get(self, token, *, session):
        return self.images.get(token)

    async def bind(self, token, order_id, *, session):
        from dataclasses import replace

        self.images[token] = replace(self.images[token], order_id=order_id)


class Store:
    def __init__(self):
        self.files = {}

    async def put(self, token, data):
        self.files[token] = data

    async def get(self, token):
        return self.files[token]

    async def delete(self, token):
        self.files.pop(token, None)


class Clock:
    def __init__(self):
        self.at = datetime(2026, 10, 30, tzinfo=timezone.utc)

    def now(self):
        return self.at


def picture(size=(1080, 1080), kind="JPEG"):
    stream = io.BytesIO()
    Image.new("RGB", size, (50, 70, 90)).save(stream, format=kind)
    return stream.getvalue()


@pytest.fixture
def image_service():
    return OrderImageService(Repo(), Store(), Tx(), Clock())


@pytest.mark.asyncio
async def test_image_upload_owner_and_expiry(image_service):
    owner, order = uuid4(), uuid4()
    image = await image_service.upload(owner, picture())
    assert await image_service.content(owner, image.token) == picture()
    with pytest.raises(PermissionError):
        await image_service.content(uuid4(), image.token)
    image_service.clock.at += timedelta(days=2)
    with pytest.raises(ValueError, match="image_expired"):
        await image_service.bind(owner, image.token, order, session=object())


@pytest.mark.asyncio
async def test_image_bound_to_order_survives_temporary_expiry(image_service):
    owner, order = uuid4(), uuid4()
    image = await image_service.upload(owner, picture())
    await image_service.bind(owner, image.token, order, session=object())
    image_service.clock.at += timedelta(days=2)
    assert await image_service.content(owner, image.token) == picture()
    await image_service.bind(owner, image.token, order, session=object())
    with pytest.raises(ValueError, match="image_already_used"):
        await image_service.bind(owner, image.token, uuid4(), session=object())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "data,reason",
    [
        (b"bad", "image_invalid"),
        (picture(kind="PNG"), "image_jpeg_required"),
        (picture((1079, 1080)), "image_dimensions"),
        (picture() + b"\0" * 5_000_000, "image_too_large"),
    ],
)
async def test_image_rejects_invalid_content(image_service, data, reason):
    with pytest.raises(ValueError, match=reason):
        await image_service.upload(uuid4(), data)
    assert not image_service.repository.images
    assert not image_service.storage.files


@pytest.mark.asyncio
async def test_exact_image_byte_limit(image_service):
    data = picture()
    data += b"\0" * (5_000_000 - len(data))
    image = await image_service.upload(uuid4(), data)
    assert image.byte_count == 5_000_000
    with pytest.raises(ValueError, match="image_too_large"):
        await image_service.upload(uuid4(), data + b"\0")


@pytest.mark.asyncio
async def test_failed_metadata_save_removes_private_blob(image_service):
    from unittest.mock import AsyncMock

    image_service.repository.save = AsyncMock(side_effect=RuntimeError("db"))
    with pytest.raises(RuntimeError, match="db"):
        await image_service.upload(uuid4(), picture())
    assert not image_service.storage.files


@pytest.mark.asyncio
async def test_changed_owner_access_during_upload_removes_blob(image_service):
    from unittest.mock import AsyncMock

    image_service.repository.authorize = AsyncMock(side_effect=[True, False])
    with pytest.raises(PermissionError, match="image_owner_required"):
        await image_service.upload(uuid4(), picture())
    assert not image_service.storage.files
    assert not image_service.repository.images


@pytest.mark.asyncio
async def test_owner_authorization_precedes_file_read_and_decode(image_service):
    from uuid import UUID

    with pytest.raises(PermissionError, match="image_owner_required"):
        await image_service.upload(UUID(int=0), b"corrupt")
    with pytest.raises(PermissionError, match="image_owner_required"):
        await image_service.content(UUID(int=0), uuid4())


@pytest.mark.asyncio
async def test_missing_expired_and_tampered_image_cannot_be_read(image_service):
    owner = uuid4()
    with pytest.raises(LookupError, match="image_not_found"):
        await image_service.content(owner, uuid4())
    image = await image_service.upload(owner, picture())
    assert await image_service.reference(owner, image.token) == image.reference
    image_service.storage.files[image.token] = b"tampered"
    with pytest.raises(ValueError, match="image_integrity_error"):
        await image_service.content(owner, image.token)
    image_service.clock.at += timedelta(days=2)
    with pytest.raises(ValueError, match="image_expired"):
        await image_service.reference(owner, image.token)


@pytest.mark.asyncio
async def test_cleanup_retains_metadata_when_file_deletion_fails(image_service):
    from unittest.mock import AsyncMock

    image = await image_service.upload(uuid4(), picture())
    image_service.repository.expired = AsyncMock(return_value=[image])
    image_service.repository.delete = AsyncMock()
    image_service.storage.delete = AsyncMock(side_effect=OSError("disk"))
    with pytest.raises(OSError, match="disk"):
        await image_service.cleanup()
    image_service.repository.delete.assert_not_awaited()
    assert image.token in image_service.repository.images


@pytest.mark.asyncio
async def test_private_storage_uses_uuid_and_private_permissions(tmp_path):
    from ugc_bot.infrastructure.order_images import (
        PrivateOrderImageStorage,
        image_path,
        telegram_order_photo,
    )

    token = uuid4()
    directory = tmp_path / "private"
    storage = PrivateOrderImageStorage(directory)
    await storage.put(token, picture())
    assert await storage.get(token) == picture()
    assert directory.stat().st_mode & 0o777 == 0o700
    assert image_path(token, directory).stat().st_mode & 0o777 == 0o600
    with pytest.raises(FileExistsError):
        await storage.put(token, b"replacement")
    assert await storage.get(token) == picture()
    assert telegram_order_photo("legacy-id", directory) == "legacy-id"
    photo = telegram_order_photo("order-image:" + str(token), directory)
    assert photo.path == image_path(token, directory)
    with pytest.raises(ValueError):
        telegram_order_photo("order-image:../secret", directory)
    await storage.delete(token)
    await storage.delete(token)
    assert not image_path(token, directory).exists()


@pytest.mark.asyncio
async def test_trusted_admin_preview_requires_actual_matching_order_binding(
    image_service,
):
    from types import SimpleNamespace

    owner, identity = uuid4(), uuid4()
    image = await image_service.upload(owner, picture())
    order = SimpleNamespace(
        order_id=identity,
        advertiser_id=owner,
        product_photo_file_id=image.reference,
    )
    with pytest.raises(LookupError):
        await image_service.attached_content(order)
    await image_service.bind(owner, image.token, identity, session=object())
    image_service.clock.at += timedelta(days=3)
    assert await image_service.attached_content(order) == picture()
    with pytest.raises(LookupError):
        await image_service.attached_content(
            SimpleNamespace(
                order_id=uuid4(),
                advertiser_id=owner,
                product_photo_file_id=image.reference,
            )
        )
    with pytest.raises(LookupError):
        await image_service.attached_content(
            SimpleNamespace(
                order_id=identity,
                advertiser_id=uuid4(),
                product_photo_file_id=image.reference,
            )
        )
    for reference in (
        "telegram-id",
        "order-image:../secret",
        "order-image:" + str(uuid4()),
    ):
        with pytest.raises(LookupError):
            await image_service.attached_content(
                SimpleNamespace(
                    order_id=identity,
                    advertiser_id=owner,
                    product_photo_file_id=reference,
                )
            )
    image_service.storage.files[image.token] = b"tampered"
    with pytest.raises(ValueError, match="image_integrity_error"):
        await image_service.attached_content(order)
