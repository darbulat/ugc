"""Validate original JPEGs and bind uploads in the order transaction."""

import hashlib
import io
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID, uuid4

from PIL import Image, UnidentifiedImageError

from ugc_bot.application.financial_ports import Clock
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.application.order_image_ports import (
    OrderImage,
    OrderImageRepository,
    OrderImageStorage,
)
from ugc_bot.application.ports import TransactionManager
from ugc_bot.domain.financial import utc

MAX_IMAGE_BYTES = 5_000_000
IMAGE_HINT = "JPEG, 1080 × 1080 px, до 5 МБ (5 000 000 байт)."


def validate_order_image(data: bytes) -> None:
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("image_too_large")
    try:
        with Image.open(io.BytesIO(data)) as source:
            if source.format != "JPEG":
                raise ValueError("image_jpeg_required")
            if source.size != (1080, 1080):
                raise ValueError("image_dimensions")
            source.verify()
        with Image.open(io.BytesIO(data)) as source:
            source.load()
    except (
        UnidentifiedImageError,
        OSError,
        Image.DecompressionBombError,
    ) as exc:
        raise ValueError("image_invalid") from exc


@dataclass
class OrderImageService:
    repository: OrderImageRepository
    storage: OrderImageStorage
    transactions: TransactionManager
    clock: Clock

    async def _authorized(self, owner, principal, session):
        if not await self.repository.authorize(
            owner, principal, session=session
        ):
            raise PermissionError("image_owner_required")

    async def upload(
        self,
        owner_id: UUID,
        data: bytes,
        *,
        principal: AuthenticatedMessengerPrincipal | None = None,
    ) -> OrderImage:
        async with self.transactions.transaction() as session:
            await self._authorized(owner_id, principal, session)
        validate_order_image(data)
        now = utc(self.clock.now())
        value = OrderImage(
            uuid4(),
            owner_id,
            len(data),
            hashlib.sha256(data).hexdigest(),
            now,
            now + timedelta(hours=24),
        )
        await self.storage.put(value.token, data)
        try:
            async with self.transactions.transaction() as session:
                await self._authorized(owner_id, principal, session)
                await self.repository.save(value, session=session)
        except Exception:
            await self.storage.delete(value.token)
            raise
        return value

    async def _load(self, owner, token, session):
        value = await self.repository.get(token, session=session)
        if value is None:
            raise LookupError("image_not_found")
        if value.owner_id != owner:
            raise PermissionError("image_owner_required")
        if value.order_id is None and utc(value.expires_at) <= utc(
            self.clock.now()
        ):
            raise ValueError("image_expired")
        return value

    async def reference(
        self,
        owner_id: UUID,
        token: UUID,
        *,
        principal: AuthenticatedMessengerPrincipal | None = None,
    ) -> str:
        async with self.transactions.transaction() as session:
            await self._authorized(owner_id, principal, session)
            value = await self._load(owner_id, token, session)
        return value.reference

    async def bind(
        self,
        owner_id: UUID,
        token: UUID,
        order_id: UUID,
        *,
        session: object,
        principal: AuthenticatedMessengerPrincipal | None = None,
    ) -> None:
        await self._authorized(owner_id, principal, session)
        value = await self._load(owner_id, token, session)
        if value.order_id is not None and value.order_id != order_id:
            raise ValueError("image_already_used")
        await self.repository.bind(token, order_id, session=session)

    async def content(
        self,
        owner_id: UUID,
        token: UUID,
        *,
        principal: AuthenticatedMessengerPrincipal | None = None,
    ) -> bytes:
        async with self.transactions.transaction() as session:
            await self._authorized(owner_id, principal, session)
            value = await self._load(owner_id, token, session)
        data = await self.storage.get(token)
        if hashlib.sha256(data).hexdigest() != value.sha256:
            raise ValueError("image_integrity_error")
        return data

    async def attached_content(self, order) -> bytes:
        """Read a saved order image for trusted, admin-authenticated callers.

        The HTTP caller must authenticate the admin first. Binding and owner
        checks prevent this route from exposing arbitrary temporary uploads.
        """
        reference = order.product_photo_file_id or ""
        try:
            if not reference.startswith("order-image:"):
                raise ValueError("legacy_image_reference")
            token = UUID(reference.removeprefix("order-image:"))
        except ValueError as exc:
            raise LookupError("image_not_found") from exc
        async with self.transactions.transaction() as session:
            value = await self.repository.get(token, session=session)
            if (
                value is None
                or value.order_id != order.order_id
                or value.owner_id != order.advertiser_id
            ):
                raise LookupError("image_not_found")
        data = await self.storage.get(token)
        if hashlib.sha256(data).hexdigest() != value.sha256:
            raise ValueError("image_integrity_error")
        return data

    async def cleanup(self) -> int:
        async with self.transactions.transaction() as session:
            values = await self.repository.expired(
                utc(self.clock.now()), session=session
            )
            for value in values:
                # Keep the expired metadata until deletion succeeds so a
                # transient filesystem error can be retried by the next sweep.
                await self.storage.delete(value.token)
                await self.repository.delete(value.token, session=session)
        return len(values)
