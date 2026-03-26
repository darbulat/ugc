from unittest.mock import AsyncMock, patch

import aiohttp
import pytest

from ugc_bot.application.messenger.dto import (
    Button,
    Invoice,
    InvoiceItem,
    Keyboard,
    KeyboardKind,
)
from ugc_bot.infrastructure.messenger.max.client import (
    MaxMessengerClient,
    _build_inline_keyboard,
)


@pytest.fixture
def mock_session():
    session = AsyncMock()
    response = AsyncMock()
    response.status = 200
    response.json = AsyncMock(return_value={"success": True})
    response.text = AsyncMock(return_value="ok")
    response.__aenter__ = AsyncMock(return_value=response)
    response.__aexit__ = AsyncMock(return_value=False)
    session.request = AsyncMock(return_value=response)
    return session


@pytest.fixture
def client(mock_session):
    return MaxMessengerClient(token="test-token", session=mock_session)


@pytest.mark.asyncio
async def test_send_text_plain(client, mock_session):
    await client.send_text(chat_id="123", text="Hello")
    mock_session.request.assert_called_once()
    args, kwargs = mock_session.request.call_args
    assert args[0] == "POST"
    assert kwargs["params"] == {"chat_id": "123"}
    assert kwargs["json"]["text"] == "Hello"


@pytest.mark.asyncio
async def test_send_text_with_inline_keyboard(client, mock_session):
    kb = Keyboard(
        kind=KeyboardKind.INLINE,
        rows=[[Button(text="Click", callback_data="btn:1")]],
    )
    await client.send_text(chat_id="123", text="Choose:", keyboard=kb)
    mock_session.request.assert_called_once()
    body = mock_session.request.call_args.kwargs["json"]
    assert "attachments" in body
    assert body["attachments"][0]["type"] == "inline_keyboard"


@pytest.mark.asyncio
async def test_send_photo_falls_back_to_text(client, mock_session):
    await client.send_photo(chat_id="123", file_id="abc", caption="My photo")
    mock_session.request.assert_called_once()
    body = mock_session.request.call_args.kwargs["json"]
    assert body["text"] == "My photo"


@pytest.mark.asyncio
async def test_send_photo_none_caption(client, mock_session):
    await client.send_photo(chat_id="123", file_id="abc", caption=None)
    body = mock_session.request.call_args.kwargs["json"]
    assert body["text"] == ""


@pytest.mark.asyncio
async def test_edit_text(client, mock_session):
    await client.edit_text(chat_id="123", message_id="msg_1", text="Updated")
    args, kwargs = mock_session.request.call_args
    assert args[0] == "PUT"
    assert kwargs["params"] == {"message_id": "msg_1"}


@pytest.mark.asyncio
async def test_answer_callback(client, mock_session):
    await client.answer_callback(callback_id="cb_1", text="Done")
    args, kwargs = mock_session.request.call_args
    assert args[0] == "POST"
    assert kwargs["params"] == {"callback_id": "cb_1"}


@pytest.mark.asyncio
async def test_send_invoice_raises(client):
    invoice = Invoice(
        title="Test",
        description="Desc",
        payload="pay_1",
        provider_token="tok",
        currency="RUB",
        items=[InvoiceItem(label="Item", amount_minor=10000)],
    )
    with pytest.raises(NotImplementedError):
        await client.send_invoice(chat_id="123", invoice=invoice)


@pytest.mark.asyncio
async def test_edit_reply_markup(client, mock_session):
    kb = Keyboard(
        kind=KeyboardKind.INLINE,
        rows=[[Button(text="New", callback_data="new:1")]],
    )
    await client.edit_reply_markup(
        chat_id="123", message_id="msg_1", keyboard=kb
    )
    args, kwargs = mock_session.request.call_args
    assert args[0] == "PUT"


@pytest.mark.asyncio
async def test_reply_keyboard_ignored(client, mock_session):
    kb = Keyboard(
        kind=KeyboardKind.REPLY,
        rows=[[Button(text="Share contact", request_contact=True)]],
    )
    await client.send_text(chat_id="123", text="Hello", keyboard=kb)
    body = mock_session.request.call_args.kwargs["json"]
    assert "attachments" not in body


@pytest.mark.asyncio
async def test_send_text_strips_html(client, mock_session):
    await client.send_text(
        chat_id="123", text="<b>Bold</b> and <i>italic</i>", parse_mode="HTML"
    )
    body = mock_session.request.call_args.kwargs["json"]
    assert body["text"] == "Bold and italic"


def test_build_inline_keyboard_url_button():
    kb = Keyboard(
        kind=KeyboardKind.INLINE,
        rows=[[Button(text="Open", url="https://example.com")]],
    )
    result = _build_inline_keyboard(kb)
    btn = result["payload"]["buttons"][0]
    assert btn["type"] == "link"
    assert btn["url"] == "https://example.com"


def test_build_inline_keyboard_request_contact():
    kb = Keyboard(
        kind=KeyboardKind.INLINE,
        rows=[[Button(text="Share", request_contact=True)]],
    )
    result = _build_inline_keyboard(kb)
    btn = result["payload"]["buttons"][0]
    assert btn["type"] == "request_contact"


def test_build_inline_keyboard_request_location():
    kb = Keyboard(
        kind=KeyboardKind.INLINE,
        rows=[[Button(text="Location", request_location=True)]],
    )
    result = _build_inline_keyboard(kb)
    btn = result["payload"]["buttons"][0]
    assert btn["type"] == "request_geo_location"


@pytest.fixture
def make_response():
    def _make(status: int):
        response = AsyncMock()
        response.status = status
        response.json = AsyncMock(return_value={"success": True})
        response.text = AsyncMock(return_value="error body")
        response.headers = {}
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=False)
        return response

    return _make


@pytest.mark.asyncio
async def test_request_403_raises_max_user_blocked_error(make_response):
    from ugc_bot.infrastructure.messenger.max.client import MaxUserBlockedError

    response = make_response(403)
    session = AsyncMock()
    session.request = AsyncMock(return_value=response)
    client = MaxMessengerClient(token="tok", session=session)
    with pytest.raises(MaxUserBlockedError):
        await client._request("GET", "/test")


@pytest.mark.asyncio
async def test_request_400_logs_and_returns_json(make_response):
    response = make_response(400)
    session = AsyncMock()
    session.request = AsyncMock(return_value=response)
    client = MaxMessengerClient(token="tok", session=session)
    result = await client._request("GET", "/test")
    assert result == {"success": True}


@pytest.mark.asyncio
async def test_request_5xx_retries_then_returns(make_response):
    ok_response = AsyncMock()
    ok_response.status = 200
    ok_response.json = AsyncMock(return_value={"ok": True})
    ok_response.text = AsyncMock(return_value="ok")
    ok_response.__aenter__ = AsyncMock(return_value=ok_response)
    ok_response.__aexit__ = AsyncMock(return_value=False)

    err_response = make_response(500)
    session = AsyncMock()
    session.request = AsyncMock(side_effect=[err_response, ok_response])
    client = MaxMessengerClient(token="tok", session=session)
    with patch(
        "ugc_bot.infrastructure.messenger.max.client.asyncio.sleep",
        new_callable=AsyncMock,
    ):
        result = await client._request("GET", "/test")
    assert result == {"ok": True}


@pytest.mark.asyncio
async def test_request_network_error_retries_then_raises(make_response):
    session = AsyncMock()
    session.request = AsyncMock(
        side_effect=aiohttp.ClientError("connection failed")
    )
    client = MaxMessengerClient(token="tok", session=session)
    with (
        patch(
            "ugc_bot.infrastructure.messenger.max.client.asyncio.sleep",
            new_callable=AsyncMock,
        ),
        pytest.raises(aiohttp.ClientError),
    ):
        await client._request("GET", "/test")


@pytest.mark.asyncio
async def test_request_5xx_all_retries_exhausted_returns_empty(make_response):
    err_response = make_response(500)
    session = AsyncMock()
    session.request = AsyncMock(return_value=err_response)
    client = MaxMessengerClient(token="tok", session=session)
    with patch(
        "ugc_bot.infrastructure.messenger.max.client.asyncio.sleep",
        new_callable=AsyncMock,
    ):
        result = await client._request("GET", "/test")
    assert result == {}


@pytest.mark.asyncio
async def test_request_429_rate_limited_then_succeeds(make_response):
    rate_limited = make_response(429)
    rate_limited.headers = {"Retry-After": "0.1"}
    ok_response = AsyncMock()
    ok_response.status = 200
    ok_response.json = AsyncMock(return_value={"ok": True})
    ok_response.text = AsyncMock(return_value="ok")
    ok_response.__aenter__ = AsyncMock(return_value=ok_response)
    ok_response.__aexit__ = AsyncMock(return_value=False)

    session = AsyncMock()
    session.request = AsyncMock(side_effect=[rate_limited, ok_response])
    client = MaxMessengerClient(token="tok", session=session)
    with patch(
        "ugc_bot.infrastructure.messenger.max.client.asyncio.sleep",
        new_callable=AsyncMock,
    ):
        result = await client._request("GET", "/test")
    assert result == {"ok": True}


@pytest.mark.asyncio
async def test_edit_text_with_keyboard(client, mock_session):
    kb = Keyboard(
        kind=KeyboardKind.INLINE, rows=[[Button(text="OK", callback_data="ok")]]
    )
    await client.edit_text(
        chat_id="123", message_id="msg_1", text="Hi", keyboard=kb
    )
    body = mock_session.request.call_args.kwargs["json"]
    assert "attachments" in body
