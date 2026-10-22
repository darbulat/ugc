"""Admin image validation, Telegram cleanup, and manager form enrichment."""

import io
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from starlette.datastructures import Headers, UploadFile

from ugc_bot.admin import app as admin


@pytest.fixture
def upload_env(monkeypatch):
    bot = NS(
        send_photo=AsyncMock(),
        delete_message=AsyncMock(),
        session=NS(close=AsyncMock()),
    )
    bot.send_photo.return_value = NS(
        photo=[NS(file_id="small"), NS(file_id="largest")],
        chat=NS(id=12),
        message_id=44,
    )
    factory = Mock(return_value=bot)
    monkeypatch.setattr(admin, "Bot", factory)
    return NS(
        bot=bot,
        factory=factory,
        config=NS(bot=NS(bot_token="unused"), market=NS(support_chat_id="12")),
        auth=NS(authenticate=AsyncMock(return_value=True)),
    )


def request_for(
    content=b"\x89PNG\r\n\x1a\npayload",
    content_type="image/png",
    filename="test.png",
):
    upload = UploadFile(
        io.BytesIO(content),
        filename=filename,
        headers=Headers({"content-type": content_type}),
    )
    return NS(form=AsyncMock(return_value={"photo": upload}))


@pytest.mark.asyncio
async def test_unauthenticated_upload_never_reads_body_or_creates_bot(
    upload_env,
):
    request = request_for()
    upload_env.auth.authenticate.return_value = False
    response = await admin._handle_order_photo_upload(
        request, upload_env.auth, upload_env.config
    )
    assert response.status_code == 401
    assert json.loads(response.body) == {"error": "Требуется вход в админку"}
    request.form.assert_not_awaited()
    upload_env.factory.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case,error",
    [
        ("missing", "Выберите PNG или JPG"),
        ("mime", "Допустимы только PNG и JPG"),
        ("size", "Максимальный размер — 10 МБ"),
        ("signature", "Файл не похож на PNG или JPG"),
    ],
)
async def test_invalid_upload_is_rejected_before_telegram(
    upload_env, case, error
):
    request = request_for()
    if case == "missing":
        request.form.return_value = {"photo": "not a file"}
    elif case == "mime":
        request = request_for(content_type="text/plain")
    elif case == "size":
        request = request_for(content=b"x" * (10 * 1024 * 1024 + 1))
    else:
        request = request_for(content=b"not PNG")
    response = await admin._handle_order_photo_upload(
        request, upload_env.auth, upload_env.config
    )
    assert response.status_code == 400
    assert json.loads(response.body) == {"error": error}
    upload_env.factory.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("jpeg", [False, True])
@pytest.mark.parametrize("delete_error", [False, True])
async def test_success_returns_largest_photo_and_always_closes_bot(
    upload_env, jpeg, delete_error, caplog
):
    content = b"\xff\xd8\xffjpeg" if jpeg else b"\x89PNG\r\n\x1a\npng"
    request = request_for(
        content, "IMAGE/JPEG" if jpeg else "image/png", filename=None
    )
    if delete_error:
        upload_env.bot.delete_message.side_effect = RuntimeError(
            "cannot delete"
        )
    response = await admin._handle_order_photo_upload(
        request, upload_env.auth, upload_env.config
    )
    assert response.status_code == 200
    assert json.loads(response.body) == {"file_id": "largest"}
    sent = upload_env.bot.send_photo.await_args.kwargs
    assert sent["chat_id"] == 12
    assert sent["photo"].data == content
    assert sent["photo"].filename == "order-image"
    upload_env.bot.delete_message.assert_awaited_once_with(
        chat_id=12, message_id=44
    )
    upload_env.bot.session.close.assert_awaited_once()
    assert (
        "Could not remove temporary order photo" in caplog.text
    ) == delete_error


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["send", "no_sizes"])
async def test_telegram_failure_is_a_gateway_error_and_closes_session(
    upload_env, failure
):
    if failure == "send":
        upload_env.bot.send_photo.side_effect = RuntimeError("remote down")
    else:
        upload_env.bot.send_photo.return_value.photo = []
    response = await admin._handle_order_photo_upload(
        request_for(), upload_env.auth, upload_env.config
    )
    assert response.status_code == 502
    error = json.loads(response.body)["error"]
    assert error == (
        "Telegram не вернул данные фотографии"
        if failure == "no_sizes"
        else "Telegram не принял фото. Проверьте права бота в чате поддержки."
    )
    assert upload_env.bot.delete_message.await_count == int(
        failure == "no_sizes"
    )
    upload_env.bot.session.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_cancelled_upload_propagates_cancellation_but_closes_bot(
    upload_env,
):
    from asyncio import CancelledError

    upload_env.bot.send_photo.side_effect = CancelledError()
    with pytest.raises(CancelledError):
        await admin._handle_order_photo_upload(
            request_for(), upload_env.auth, upload_env.config
        )
    upload_env.bot.session.close.assert_awaited_once()
    upload_env.bot.delete_message.assert_not_awaited()


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, ""),
        ("short", "short"),
        ("x" * 50, "x" * 50),
        ("ю" * 51, "ю" * 50 + "…"),
    ],
)
def test_truncation_respects_fifty_unicode_characters(value, expected):
    assert admin._truncate_50(value) == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode",
    ["populated", "no_tm", "no_container", "failure", "irrelevant", "no_model"],
)
async def test_manager_form_enrichment_preserves_only_known_usernames(
    monkeypatch, mode, caplog
):
    session = object()
    transactions = []

    @asynccontextmanager
    async def transaction():
        transactions.append("begin")
        try:
            yield session
        finally:
            transactions.append("end")

    manager_repo = NS(
        list_by_order=AsyncMock(return_value=[NS(user_id=i) for i in range(3)])
    )
    user_repo = NS(
        get_by_id=AsyncMock(
            side_effect=[NS(telegram="alice"), None, NS(telegram=None)]
        )
    )
    service = NS(manager_order_repo=manager_repo, user_repo=user_repo)
    container = NS(
        build_manager_service=Mock(return_value=service),
        transaction_manager=NS(transaction=transaction)
        if mode != "no_tm"
        else None,
    )
    if mode == "failure":
        manager_repo.list_by_order.side_effect = RuntimeError(
            "repository unavailable"
        )
    monkeypatch.setattr(
        admin, "_admin_container", None if mode == "no_container" else container
    )
    model = None if mode == "no_model" else NS(order_id=uuid4())
    view = object() if mode == "irrelevant" else admin.OrderAdmin()
    context = {"unchanged": "value"}
    await admin._inject_order_managers(context, view, model)
    assert context == (
        {"unchanged": "value", "managers_value": "@alice"}
        if mode == "populated"
        else {"unchanged": "value", "managers_value": ""}
        if mode == "no_tm"
        else {"unchanged": "value"}
    )
    if mode in {"populated", "failure"}:
        assert transactions == ["begin", "end"]
        manager_repo.list_by_order.assert_awaited_once_with(
            model.order_id, session=session
        )
    else:
        manager_repo.list_by_order.assert_not_awaited()
    if mode == "populated":
        assert [
            call.args[0] for call in user_repo.get_by_id.await_args_list
        ] == [0, 1, 2]
        assert all(
            call.kwargs == {"session": session}
            for call in user_repo.get_by_id.await_args_list
        )
    if mode == "failure":
        assert "Failed to inject order managers" in caplog.text


@pytest.mark.asyncio
async def test_eligible_count_does_not_modify_other_admin_views():
    context = {"existing": 12}
    await admin._inject_order_eligible_bloggers_count(
        context, object(), object()
    )
    assert context == {"existing": 12}
