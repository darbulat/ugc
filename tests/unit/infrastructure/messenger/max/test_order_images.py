"""MAX photo delivery uses private bytes and real multipart request encoding."""

import io
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from PIL import Image

from ugc_bot.application.messenger.dto import Button, Keyboard, KeyboardKind
from ugc_bot.infrastructure.messenger.max.client import (
    MaxAPIError,
    MaxMessengerClient,
)
from ugc_bot.infrastructure.order_images import PrivateOrderImageStorage


def response(payload, status=200):
    result = AsyncMock()
    result.status = status
    result.json.return_value = payload
    result.text.return_value = "{}"
    result.__aenter__.return_value = result
    return result


@pytest.mark.asyncio
async def test_private_photo_uses_multipart_upload_and_received_token(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("ORDER_IMAGE_DIRECTORY", str(tmp_path))
    data = io.BytesIO()
    Image.new("RGB", (1080, 1080)).save(data, "JPEG")
    token = uuid4()
    await PrivateOrderImageStorage().put(token, data.getvalue())
    session = AsyncMock()
    session.request.side_effect = [
        response({"url": "https://iu.oneme.ru/uploadImage?r=synthetic"}),
        response(
            {"photos": {"synthetic-id": {"token": "received-image-token"}}}
        ),
        response({"success": True}),
    ]
    client = MaxMessengerClient("private-bot-token", session)
    keyboard = Keyboard(
        KeyboardKind.INLINE, [[Button("Choose", callback_data="choose")]]
    )
    await client.send_photo(
        chat_id="42",
        file_id="order-image:" + str(token),
        caption="<b>Brief</b>",
        keyboard=keyboard,
        parse_mode="HTML",
    )
    create, upload, send = session.request.call_args_list
    assert create.args == ("POST", "https://platform-api2.max.ru/uploads")
    assert create.kwargs["params"] == {"type": "image"}
    assert upload.args == (
        "POST",
        "https://iu.oneme.ru/uploadImage?r=synthetic",
    )
    assert upload.kwargs["allow_redirects"] is False
    encoded = []
    writer = AsyncMock()
    writer.write.side_effect = lambda chunk: encoded.append(chunk)
    await upload.kwargs["data"]().write(writer)
    multipart = b"".join(encoded)
    assert b'name="data"' in multipart and b"image/jpeg" in multipart
    assert data.getvalue() in multipart
    assert send.kwargs["json"]["attachments"][0] == {
        "type": "image",
        "payload": {"token": "received-image-token"},
    }
    assert send.kwargs["json"]["attachments"][1]["type"] == "inline_keyboard"
    assert send.kwargs["json"]["format"] == "html"
    assert "order-image:" not in str(send.kwargs)


@pytest.mark.asyncio
async def test_legacy_photo_preserves_caption_without_remote_fetch():
    session = AsyncMock()
    session.request.return_value = response({"success": True})
    await MaxMessengerClient("token", session).send_photo(
        chat_id="42", file_id="telegram-file-id", caption="Brief"
    )
    assert session.request.await_count == 1
    assert session.request.call_args.args[1].endswith("/messages")
    assert session.request.call_args.kwargs["json"] == {"text": "Brief"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        None,
        "http://iu.oneme.ru/x",
        "https://evil.test/x",
        "https://bot:secret@iu.oneme.ru/x",
        "https://iu.oneme.ru:8443/x",
    ],
)
async def test_private_upload_rejects_non_provider_destination(
    tmp_path, monkeypatch, url
):
    monkeypatch.setenv("ORDER_IMAGE_DIRECTORY", str(tmp_path))
    token = uuid4()
    await PrivateOrderImageStorage().put(token, b"private")
    session = AsyncMock()
    session.request.return_value = response({"url": url})
    with pytest.raises(ValueError, match="max_image_upload_url_invalid"):
        await MaxMessengerClient("secret", session).send_photo(
            chat_id="42", file_id="order-image:" + str(token)
        )
    assert session.request.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "result",
    [
        {},
        {"photos": []},
        {"photos": {"one": {}}},
        {"photos": {"one": {"token": " "}}},
        {"photos": {"one": {"token": 5}}},
        {"photos": {"one": {"token": "a"}, "two": {"token": "b"}}},
    ],
)
async def test_private_upload_requires_one_actual_attachment_token(
    tmp_path, monkeypatch, result
):
    monkeypatch.setenv("ORDER_IMAGE_DIRECTORY", str(tmp_path))
    token = uuid4()
    await PrivateOrderImageStorage().put(token, b"private")
    session = AsyncMock()
    session.request.side_effect = [
        response({"url": "https://iu.oneme.ru/image"}),
        response(result),
    ]
    with pytest.raises(ValueError, match="max_image_upload_token_missing"):
        await MaxMessengerClient("token", session).send_photo(
            chat_id="42", file_id="order-image:" + str(token)
        )
    assert session.request.await_count == 2


@pytest.mark.asyncio
async def test_upload_failure_and_missing_image_do_not_send(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("ORDER_IMAGE_DIRECTORY", str(tmp_path))
    token = uuid4()
    session = AsyncMock()
    client = MaxMessengerClient("token", session)
    with pytest.raises(FileNotFoundError):
        await client.send_photo(
            chat_id="42", file_id="order-image:" + str(token)
        )
    session.request.assert_not_awaited()
    with pytest.raises(ValueError):
        await client.send_photo(
            chat_id="42", file_id="order-image:../../secret"
        )
    session.request.assert_not_awaited()
    await PrivateOrderImageStorage().put(token, b"private")
    session.request.side_effect = [
        response({"url": "https://iu.oneme.ru/image"}),
        response({}, 500),
    ]
    with pytest.raises(MaxAPIError, match="max_image_upload_failed"):
        await client.send_photo(
            chat_id="42", file_id="order-image:" + str(token)
        )
    assert session.request.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["ready", "exhausted", "rejected"])
async def test_only_explicit_attachment_not_ready_is_retried(
    tmp_path, monkeypatch, outcome
):
    from ugc_bot.infrastructure.messenger.max import client as module

    monkeypatch.setenv("ORDER_IMAGE_DIRECTORY", str(tmp_path))
    monkeypatch.setattr(module.asyncio, "sleep", AsyncMock())
    token = uuid4()
    await PrivateOrderImageStorage().put(token, b"private")
    not_ready = response({}, 400)
    not_ready.text.return_value = '{"code":"attachment.not.ready"}'
    rejected = response({}, 400)
    rejected.text.return_value = '{"code":"attachment.invalid"}'
    replies = [
        response({"url": "https://iu.oneme.ru/image"}),
        response({"photos": {"one": {"token": "image-token"}}}),
    ]
    replies += (
        [not_ready, response({})]
        if outcome == "ready"
        else [not_ready] * 3
        if outcome == "exhausted"
        else [rejected]
    )
    session = AsyncMock()
    session.request.side_effect = replies
    call = MaxMessengerClient("token", session).send_photo(
        chat_id="42", file_id="order-image:" + str(token)
    )
    if outcome == "ready":
        await call
    else:
        with pytest.raises(MaxAPIError):
            await call
    assert session.request.await_count == len(replies)
    assert (
        module.asyncio.sleep.await_count
        == {"ready": 1, "exhausted": 2, "rejected": 0}[outcome]
    )
