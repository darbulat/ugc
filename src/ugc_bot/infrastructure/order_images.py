"""Private local attachment volume; only canonical UUID filenames are used."""

import asyncio
import os
from pathlib import Path
from uuid import UUID

from aiogram.types import FSInputFile


def image_directory() -> Path:
    return Path(os.environ.get("ORDER_IMAGE_DIRECTORY", "var/order-images"))


def image_path(token: UUID, directory: Path | None = None) -> Path:
    return (directory or image_directory()) / f"{UUID(str(token))}.jpg"


def telegram_order_photo(reference: str, directory: Path | None = None):
    if reference.startswith("order-image:"):
        token = UUID(reference.removeprefix("order-image:"))
        return FSInputFile(image_path(token, directory))
    return reference


class PrivateOrderImageStorage:
    def __init__(self, directory: Path | None = None):
        self.directory = directory or image_directory()

    async def put(self, token: UUID, data: bytes) -> None:
        def write():
            self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            path = image_path(token, self.directory)
            descriptor = os.open(
                path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
            )
            with os.fdopen(descriptor, "wb") as output:
                output.write(data)

        await asyncio.to_thread(write)

    async def get(self, token: UUID) -> bytes:
        return await asyncio.to_thread(
            image_path(token, self.directory).read_bytes
        )

    async def delete(self, token: UUID) -> None:
        await asyncio.to_thread(
            image_path(token, self.directory).unlink, missing_ok=True
        )
