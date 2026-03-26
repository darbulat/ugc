"""Max messenger client — sends messages via Max Platform API."""

import asyncio
import logging
import re
from typing import Any

import aiohttp

from ugc_bot.application.messenger.dto import (
    Invoice,
    Keyboard,
    KeyboardKind,
)
from ugc_bot.application.messenger.ports import MessengerClient

logger = logging.getLogger(__name__)

MAX_API_BASE_URL = "https://platform-api.max.ru"


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


MAX_RETRY_ATTEMPTS = 3
MAX_RETRY_BASE_DELAY = 0.5

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    return _HTML_TAG_RE.sub("", text)


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
                max_btn["url"] = btn.web_app_url
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
                        text = await resp.text()
                        logger.error(
                            "Max API 5xx error %s: %s", resp.status, text
                        )
                        await asyncio.sleep(MAX_RETRY_BASE_DELAY * (2**attempt))
                        continue
                    if resp.status >= 400:
                        text = await resp.text()
                        logger.error("Max API error %s: %s", resp.status, text)
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
        )

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
        clean_text = (
            _strip_html(text)
            if parse_mode and "html" in parse_mode.lower()
            else text
        )
        body: dict[str, Any] = {"text": clean_text}
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
        text = caption or ""
        await self.send_text(chat_id=chat_id, text=text, keyboard=keyboard)

    async def edit_text(
        self,
        *,
        chat_id: str,
        message_id: str,
        text: str,
        keyboard: Keyboard | None = None,
        parse_mode: str | None = None,
    ) -> None:
        clean_text = (
            _strip_html(text)
            if parse_mode and "html" in parse_mode.lower()
            else text
        )
        body: dict[str, Any] = {"text": clean_text}
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

    async def send_invoice(self, *, chat_id: str, invoice: Invoice) -> None:
        raise NotImplementedError(
            "Max messenger does not support payments. "
            "Check messenger_type before calling send_invoice."
        )
