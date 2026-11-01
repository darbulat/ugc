"""Max messenger client — sends messages via Max Platform API."""

import asyncio
import json
import logging
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import aiohttp

from ugc_bot.application.messenger.dto import (
    Invoice,
    Keyboard,
    KeyboardKind,
)
from ugc_bot.application.messenger.ports import MessengerClient
from ugc_bot.infrastructure.order_images import PrivateOrderImageStorage

logger = logging.getLogger(__name__)

MAX_API_BASE_URL = "https://platform-api2.max.ru"


class MaxAPIError(Exception):
    """Raised on non-retriable Max API errors (4xx except 403/429)."""

    def __init__(self, status: int, body: str) -> None:
        self.status = status
        self.body = body
        super().__init__(f"Max API error {status}: {body}")


class MaxUserBlockedError(MaxAPIError):
    """Raised when Max API returns 403 (user blocked the bot)."""

    def __init__(self, body: str) -> None:
        super().__init__(403, body)


class MaxChatNotFoundError(MaxAPIError):
    """Raised when Max API reports that target chat no longer exists."""

    def __init__(self, body: str) -> None:
        super().__init__(404, body)


MAX_RETRY_ATTEMPTS = 3
MAX_RETRY_BASE_DELAY = 0.5


def _is_chat_not_found_error(body: str) -> bool:
    """Return True when response body indicates Max chat.not.found."""
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        code = parsed.get("code")
        if isinstance(code, str) and code == "chat.not.found":
            return True
    return '"code":"chat.not.found"' in body.replace(" ", "")


def _build_inline_keyboard(keyboard: Keyboard) -> dict[str, Any]:
    rows: list[list[dict[str, Any]]] = []
    for row in keyboard.rows:
        max_row: list[dict[str, Any]] = []
        for btn in row:
            max_btn: dict[str, Any] = {
                "text": btn.text,
                "type": "callback",
            }
            if btn.web_app_url:
                max_btn["type"] = "open_app"
                max_btn["web_app"] = btn.web_app_url
                if btn.max_app_payload:
                    max_btn["payload"] = btn.max_app_payload
            elif btn.callback_data:
                max_btn["type"] = "callback"
                max_btn["payload"] = btn.callback_data
            elif btn.url:
                max_btn["type"] = "link"
                max_btn["url"] = btn.url
            elif btn.request_contact:
                max_btn["type"] = "request_contact"
            elif btn.request_location:
                max_btn["type"] = "request_geo_location"
            max_row.append(max_btn)
        rows.append(max_row)
    return {"type": "inline_keyboard", "payload": {"buttons": rows}}


class MaxMessengerClient(MessengerClient):
    def __init__(self, token: str, session: aiohttp.ClientSession) -> None:
        self._token = token
        self._session = session
        self._base_url = MAX_API_BASE_URL

    async def _request(
        self,
        method: str,
        path: str,
        json_body: dict | None = None,
        params: dict[str, str] | None = None,
    ) -> dict:
        url = f"{self._base_url}{path}"
        headers = {"Authorization": self._token}
        last_exc: Exception | None = None
        last_body: str | None = None

        for attempt in range(MAX_RETRY_ATTEMPTS):
            try:
                resp = await self._session.request(
                    method, url, json=json_body, headers=headers, params=params
                )
                async with resp:
                    if resp.status == 429:
                        retry_after = float(
                            resp.headers.get("Retry-After", "1")
                        )
                        logger.warning(
                            "Max API rate limited, retry after %s s",
                            retry_after,
                        )
                        await asyncio.sleep(retry_after)
                        continue
                    if resp.status == 403:
                        text = await resp.text()
                        logger.warning(
                            "Max API 403 (user blocked bot?): %s", text
                        )
                        raise MaxUserBlockedError(text)
                    if resp.status >= 500:
                        last_body = await resp.text()
                        logger.error(
                            "Max API 5xx error %s: %s",
                            resp.status,
                            last_body,
                        )
                        await asyncio.sleep(MAX_RETRY_BASE_DELAY * (2**attempt))
                        continue
                    if resp.status >= 400:
                        text = await resp.text()
                        logger.error("Max API error %s: %s", resp.status, text)
                        if resp.status == 404 and _is_chat_not_found_error(
                            text
                        ):
                            raise MaxChatNotFoundError(text)
                        raise MaxAPIError(resp.status, text)
                    return await resp.json()
            except aiohttp.ClientError as exc:
                last_exc = exc
                logger.error(
                    "Max API network error (attempt %d): %s", attempt + 1, exc
                )
                await asyncio.sleep(MAX_RETRY_BASE_DELAY * (2**attempt))

        logger.error(
            "Max API request failed after %d attempts: %s %s",
            MAX_RETRY_ATTEMPTS,
            method,
            path,
        )
        if last_exc:
            raise last_exc
        raise RuntimeError(
            f"Max API request {method} {path} failed after "
            f"{MAX_RETRY_ATTEMPTS} attempts"
            f"{f': {last_body}' if last_body else ''}"
        )

    async def _patch(
        self,
        path: str,
        json_body: dict | None = None,
        params: dict[str, str] | None = None,
    ) -> dict:
        return await self._request("PATCH", path, json_body, params=params)

    async def _post(
        self,
        path: str,
        json_body: dict | None = None,
        params: dict[str, str] | None = None,
    ) -> dict:
        return await self._request("POST", path, json_body, params=params)

    async def _put(
        self,
        path: str,
        json_body: dict | None = None,
        params: dict[str, str] | None = None,
    ) -> dict:
        return await self._request("PUT", path, json_body, params=params)

    async def send_text(
        self,
        *,
        chat_id: str,
        text: str,
        keyboard: Keyboard | None = None,
        parse_mode: str | None = None,
        disable_preview: bool | None = None,
    ) -> None:
        body: dict[str, Any] = {"text": text}
        if parse_mode and "html" in parse_mode.lower():
            body["format"] = "html"
        if keyboard and keyboard.kind == KeyboardKind.INLINE:
            body["attachments"] = [_build_inline_keyboard(keyboard)]
        await self._post("/messages", body, params={"chat_id": chat_id})

    async def send_photo(
        self,
        *,
        chat_id: str,
        file_id: str,
        caption: str | None = None,
        keyboard: Keyboard | None = None,
        parse_mode: str | None = None,
    ) -> None:
        if not file_id.startswith("order-image:"):
            # Historical IDs belong to Telegram; MAX cannot resolve them.
            await self.send_text(
                chat_id=chat_id,
                text=caption or "",
                keyboard=keyboard,
                parse_mode=parse_mode,
            )
            return
        token = await self._upload_order_image(file_id)
        body: dict[str, Any] = {
            "text": caption or "",
            "attachments": [{"type": "image", "payload": {"token": token}}],
        }
        if parse_mode and "html" in parse_mode.lower():
            body["format"] = "html"
        if keyboard and keyboard.kind == KeyboardKind.INLINE:
            body["attachments"].append(_build_inline_keyboard(keyboard))
        for attempt in range(MAX_RETRY_ATTEMPTS):
            try:
                await self._post("/messages", body, params={"chat_id": chat_id})
                return
            except MaxAPIError as exc:
                # MAX can reject an uploaded image until processing completes.
                # Only this explicit rejection is safe to retry here.
                if (
                    '"attachment.not.ready"' not in exc.body
                    or attempt == MAX_RETRY_ATTEMPTS - 1
                ):
                    raise
                await asyncio.sleep(MAX_RETRY_BASE_DELAY * (2**attempt))

    async def _upload_order_image(self, reference: str) -> str:
        token = UUID(reference.removeprefix("order-image:"))
        data = await PrivateOrderImageStorage().get(token)
        upload = await self._post("/uploads", params={"type": "image"})
        url = upload.get("url")
        upload_url = url if isinstance(url, str) else ""
        target = urlsplit(upload_url)
        if (
            target.scheme != "https"
            or target.hostname != "iu.oneme.ru"
            or target.username
            or target.password
            or target.port not in (None, 443)
        ):
            raise ValueError("max_image_upload_url_invalid")
        form = aiohttp.FormData()
        form.add_field(
            "data", data, filename=f"{token}.jpg", content_type="image/jpeg"
        )
        response = await self._session.request(
            "POST",
            upload_url,
            data=form,
            headers={"Authorization": self._token},
            allow_redirects=False,
        )
        async with response:
            if not 200 <= response.status < 300:
                raise MaxAPIError(response.status, "max_image_upload_failed")
            result = await response.json(content_type=None)
        photos = result.get("photos", {})
        values = list(photos.values()) if isinstance(photos, dict) else []
        received = (
            values[0].get("token")
            if len(values) == 1 and isinstance(values[0], dict)
            else None
        )
        if not isinstance(received, str) or not received.strip():
            raise ValueError("max_image_upload_token_missing")
        return received

    async def edit_text(
        self,
        *,
        chat_id: str,
        message_id: str,
        text: str,
        keyboard: Keyboard | None = None,
        parse_mode: str | None = None,
    ) -> None:
        body: dict[str, Any] = {"text": text}
        if parse_mode and "html" in parse_mode.lower():
            body["format"] = "html"
        if keyboard and keyboard.kind == KeyboardKind.INLINE:
            body["attachments"] = [_build_inline_keyboard(keyboard)]
        else:
            # Explicitly send empty attachments to remove inline keyboard
            body["attachments"] = []
        await self._put("/messages", body, params={"message_id": message_id})

    async def edit_reply_markup(
        self,
        *,
        chat_id: str,
        message_id: str,
        keyboard: Keyboard | None = None,
    ) -> None:
        body: dict[str, Any] = {}
        if keyboard and keyboard.kind == KeyboardKind.INLINE:
            body["attachments"] = [_build_inline_keyboard(keyboard)]
        else:
            # Explicitly send empty attachments to remove inline keyboard
            body["attachments"] = []
        await self._put("/messages", body, params={"message_id": message_id})

    async def answer_callback(
        self,
        *,
        callback_id: str,
        text: str | None = None,
        show_alert: bool = False,
    ) -> None:
        body: dict[str, Any] = {"notification": text or ""}
        await self._post("/answers", body, params={"callback_id": callback_id})

    async def set_my_commands(self, commands: list[dict[str, str]]) -> None:
        """Set bot command suggestions via PATCH /me/commands."""
        await self._patch("/me/commands", {"commands": commands})

    async def send_invoice(self, *, chat_id: str, invoice: Invoice) -> None:
        raise NotImplementedError(
            "Max messenger does not support payments. "
            "Check messenger_type before calling send_invoice."
        )
