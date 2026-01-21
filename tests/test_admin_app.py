"""Tests for admin app setup."""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import FastAPI
import pytest
from sqlalchemy import create_engine
from unittest.mock import AsyncMock, MagicMock, patch

from ugc_bot.admin.app import (
    ComplaintAdmin,
    InteractionAdmin,
    UserAdmin,
    _get_services,
    create_admin_app,
)
from ugc_bot.domain.enums import ComplaintStatus, InteractionStatus, UserStatus
from ugc_bot.infrastructure.db.models import (
    ComplaintModel,
    InteractionModel,
    UserModel,
)


class AsyncContextManager:
    """Async context manager for session.begin()."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        return None


def test_create_admin_app(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure admin app is created and mounted."""

    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "password")
    monkeypatch.setenv("ADMIN_SECRET", "secret")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pass@localhost/db")

    app = create_admin_app()
    assert isinstance(app, FastAPI)
    assert any(getattr(route, "path", "") == "/admin" for route in app.routes)


def test_get_services() -> None:
    """Test _get_services function creates services correctly."""

    engine = create_engine("sqlite:///:memory:")
    user_service, complaint_service, interaction_service = _get_services(engine)

    assert user_service is not None
    assert complaint_service is not None
    assert interaction_service is not None


@pytest.mark.asyncio
async def test_user_admin_update_model_status_change() -> None:
    """Test UserAdmin.update_model handles status change to BLOCKED."""

    user_id = UUID("00000000-0000-0000-0000-000000000001")
    old_user = UserModel(
        user_id=user_id,
        external_id="123",
        messenger_type="telegram",
        username="test_user",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    new_user = UserModel(
        user_id=user_id,
        external_id="123",
        messenger_type="telegram",
        username="test_user",
        status=UserStatus.BLOCKED,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )

    mock_session = MagicMock()
    mock_session.begin = MagicMock(return_value=AsyncContextManager())
    mock_session.get = AsyncMock(side_effect=[old_user, new_user])

    admin = UserAdmin()
    admin.session = mock_session  # type: ignore[attr-defined]

    request = MagicMock()
    data = {"status": UserStatus.BLOCKED}

    with patch.object(UserAdmin.__bases__[0], "update_model", new_callable=AsyncMock):
        await admin.update_model(request, str(user_id), data)

    assert mock_session.get.call_count == 2


@pytest.mark.asyncio
async def test_interaction_admin_update_model_resolve_issue() -> None:
    """Test InteractionAdmin.update_model resolves ISSUE to OK."""

    interaction_id = UUID("00000000-0000-0000-0000-000000000002")
    old_interaction = InteractionModel(
        interaction_id=interaction_id,
        order_id=UUID("00000000-0000-0000-0000-000000000003"),
        blogger_id=UUID("00000000-0000-0000-0000-000000000004"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000005"),
        status=InteractionStatus.ISSUE,
        from_advertiser="⚠️ Проблема",
        from_blogger="⚠️ Проблема",
        postpone_count=0,
        next_check_at=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    new_interaction = InteractionModel(
        interaction_id=interaction_id,
        order_id=old_interaction.order_id,
        blogger_id=old_interaction.blogger_id,
        advertiser_id=old_interaction.advertiser_id,
        status=InteractionStatus.OK,
        from_advertiser=old_interaction.from_advertiser,
        from_blogger=old_interaction.from_blogger,
        postpone_count=old_interaction.postpone_count,
        next_check_at=None,
        created_at=old_interaction.created_at,
        updated_at=datetime.now(timezone.utc),
    )

    mock_session = MagicMock()
    mock_session.begin = MagicMock(return_value=AsyncContextManager())
    mock_session.get = AsyncMock(side_effect=[old_interaction, new_interaction])

    mock_engine = MagicMock()
    mock_engine.url = MagicMock()
    mock_engine.url.render_as_string = MagicMock(return_value="sqlite:///:memory:")

    admin = InteractionAdmin()
    admin.session = mock_session  # type: ignore[attr-defined]
    admin._engine = mock_engine  # type: ignore[attr-defined]

    request = MagicMock()
    data = {"status": InteractionStatus.OK}

    mock_interaction_service = MagicMock()
    mock_interaction_service.manually_resolve_issue = MagicMock()

    with patch.object(
        InteractionAdmin.__bases__[0], "update_model", new_callable=AsyncMock
    ), patch("ugc_bot.admin.app._get_services") as mock_get_services:
        mock_get_services.return_value = (None, None, mock_interaction_service)
        await admin.update_model(request, str(interaction_id), data)

    assert mock_session.get.call_count == 2
    mock_interaction_service.manually_resolve_issue.assert_called_once_with(
        interaction_id, InteractionStatus.OK
    )


@pytest.mark.asyncio
async def test_interaction_admin_update_model_resolve_issue_no_deal() -> None:
    """Test InteractionAdmin.update_model resolves ISSUE to NO_DEAL."""

    interaction_id = UUID("00000000-0000-0000-0000-000000000012")
    old_interaction = InteractionModel(
        interaction_id=interaction_id,
        order_id=UUID("00000000-0000-0000-0000-000000000013"),
        blogger_id=UUID("00000000-0000-0000-0000-000000000014"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000015"),
        status=InteractionStatus.ISSUE,
        from_advertiser="⚠️ Проблема",
        from_blogger="⚠️ Проблема",
        postpone_count=0,
        next_check_at=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    new_interaction = InteractionModel(
        interaction_id=interaction_id,
        order_id=old_interaction.order_id,
        blogger_id=old_interaction.blogger_id,
        advertiser_id=old_interaction.advertiser_id,
        status=InteractionStatus.NO_DEAL,
        from_advertiser=old_interaction.from_advertiser,
        from_blogger=old_interaction.from_blogger,
        postpone_count=old_interaction.postpone_count,
        next_check_at=None,
        created_at=old_interaction.created_at,
        updated_at=datetime.now(timezone.utc),
    )

    mock_session = MagicMock()
    mock_session.begin = MagicMock(return_value=AsyncContextManager())
    mock_session.get = AsyncMock(side_effect=[old_interaction, new_interaction])

    mock_engine = MagicMock()
    mock_engine.url = MagicMock()
    mock_engine.url.render_as_string = MagicMock(return_value="sqlite:///:memory:")

    admin = InteractionAdmin()
    admin.session = mock_session  # type: ignore[attr-defined]
    admin._engine = mock_engine  # type: ignore[attr-defined]

    request = MagicMock()
    data = {"status": InteractionStatus.NO_DEAL}

    mock_interaction_service = MagicMock()
    mock_interaction_service.manually_resolve_issue = MagicMock()

    with patch.object(
        InteractionAdmin.__bases__[0], "update_model", new_callable=AsyncMock
    ), patch("ugc_bot.admin.app._get_services") as mock_get_services:
        mock_get_services.return_value = (None, None, mock_interaction_service)
        await admin.update_model(request, str(interaction_id), data)

    assert mock_session.get.call_count == 2
    mock_interaction_service.manually_resolve_issue.assert_called_once_with(
        interaction_id, InteractionStatus.NO_DEAL
    )


@pytest.mark.asyncio
async def test_complaint_admin_update_model_action_taken() -> None:
    """Test ComplaintAdmin.update_model blocks user when status changes to ACTION_TAKEN."""

    complaint_id = UUID("00000000-0000-0000-0000-000000000006")
    reported_id = UUID("00000000-0000-0000-0000-000000000007")
    old_complaint = ComplaintModel(
        complaint_id=complaint_id,
        reporter_id=UUID("00000000-0000-0000-0000-000000000008"),
        reported_id=reported_id,
        order_id=UUID("00000000-0000-0000-0000-000000000009"),
        reason="Мошенничество",
        status=ComplaintStatus.PENDING,
        created_at=datetime.now(timezone.utc),
        reviewed_at=None,
    )
    new_complaint = ComplaintModel(
        complaint_id=complaint_id,
        reporter_id=old_complaint.reporter_id,
        reported_id=old_complaint.reported_id,
        order_id=old_complaint.order_id,
        reason=old_complaint.reason,
        status=ComplaintStatus.ACTION_TAKEN,
        created_at=old_complaint.created_at,
        reviewed_at=datetime.now(timezone.utc),
    )

    mock_session = MagicMock()
    mock_session.begin = MagicMock(return_value=AsyncContextManager())
    mock_session.get = AsyncMock(side_effect=[old_complaint, new_complaint])

    mock_engine = MagicMock()
    mock_engine.url = MagicMock()
    mock_engine.url.render_as_string = MagicMock(return_value="sqlite:///:memory:")

    admin = ComplaintAdmin()
    admin.session = mock_session  # type: ignore[attr-defined]
    admin._engine = mock_engine  # type: ignore[attr-defined]

    request = MagicMock()
    data = {"status": ComplaintStatus.ACTION_TAKEN}

    mock_user_service = MagicMock()
    mock_user_service.update_status = MagicMock()
    mock_complaint_service = MagicMock()
    mock_complaint_service.resolve_complaint_with_action = MagicMock()

    with patch.object(
        ComplaintAdmin.__bases__[0], "update_model", new_callable=AsyncMock
    ), patch("ugc_bot.admin.app._get_services") as mock_get_services:
        mock_get_services.return_value = (
            mock_user_service,
            mock_complaint_service,
            None,
        )
        await admin.update_model(request, str(complaint_id), data)

    assert mock_session.get.call_count == 2
    mock_complaint_service.resolve_complaint_with_action.assert_called_once_with(
        complaint_id
    )
    mock_user_service.update_status.assert_called_once_with(
        reported_id, UserStatus.BLOCKED
    )


@pytest.mark.asyncio
async def test_complaint_admin_update_model_dismissed() -> None:
    """Test ComplaintAdmin.update_model dismisses complaint when status changes to DISMISSED."""

    complaint_id = UUID("00000000-0000-0000-0000-000000000010")
    old_complaint = ComplaintModel(
        complaint_id=complaint_id,
        reporter_id=UUID("00000000-0000-0000-0000-000000000011"),
        reported_id=UUID("00000000-0000-0000-0000-000000000012"),
        order_id=UUID("00000000-0000-0000-0000-000000000013"),
        reason="Мошенничество",
        status=ComplaintStatus.PENDING,
        created_at=datetime.now(timezone.utc),
        reviewed_at=None,
    )
    new_complaint = ComplaintModel(
        complaint_id=complaint_id,
        reporter_id=old_complaint.reporter_id,
        reported_id=old_complaint.reported_id,
        order_id=old_complaint.order_id,
        reason=old_complaint.reason,
        status=ComplaintStatus.DISMISSED,
        created_at=old_complaint.created_at,
        reviewed_at=datetime.now(timezone.utc),
    )

    mock_session = MagicMock()
    mock_session.begin = MagicMock(return_value=AsyncContextManager())
    mock_session.get = AsyncMock(side_effect=[old_complaint, new_complaint])

    mock_engine = MagicMock()
    mock_engine.url = MagicMock()
    mock_engine.url.render_as_string = MagicMock(return_value="sqlite:///:memory:")

    admin = ComplaintAdmin()
    admin.session = mock_session  # type: ignore[attr-defined]
    admin._engine = mock_engine  # type: ignore[attr-defined]

    request = MagicMock()
    data = {"status": ComplaintStatus.DISMISSED}

    mock_complaint_service = MagicMock()
    mock_complaint_service.dismiss_complaint = MagicMock()

    with patch.object(
        ComplaintAdmin.__bases__[0], "update_model", new_callable=AsyncMock
    ), patch("ugc_bot.admin.app._get_services") as mock_get_services:
        mock_get_services.return_value = (None, mock_complaint_service, None)
        await admin.update_model(request, str(complaint_id), data)

    assert mock_session.get.call_count == 2
    mock_complaint_service.dismiss_complaint.assert_called_once_with(complaint_id)


@pytest.mark.asyncio
async def test_interaction_admin_update_model_no_engine() -> None:
    """Test InteractionAdmin.update_model handles missing engine gracefully."""

    interaction_id = UUID("00000000-0000-0000-0000-000000000016")
    old_interaction = InteractionModel(
        interaction_id=interaction_id,
        order_id=UUID("00000000-0000-0000-0000-000000000017"),
        blogger_id=UUID("00000000-0000-0000-0000-000000000018"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000000019"),
        status=InteractionStatus.ISSUE,
        from_advertiser="⚠️ Проблема",
        from_blogger="⚠️ Проблема",
        postpone_count=0,
        next_check_at=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    new_interaction = InteractionModel(
        interaction_id=interaction_id,
        order_id=old_interaction.order_id,
        blogger_id=old_interaction.blogger_id,
        advertiser_id=old_interaction.advertiser_id,
        status=InteractionStatus.OK,
        from_advertiser=old_interaction.from_advertiser,
        from_blogger=old_interaction.from_blogger,
        postpone_count=old_interaction.postpone_count,
        next_check_at=None,
        created_at=old_interaction.created_at,
        updated_at=datetime.now(timezone.utc),
    )

    mock_session = MagicMock()
    mock_session.begin = MagicMock(return_value=AsyncContextManager())
    mock_session.get = AsyncMock(side_effect=[old_interaction, new_interaction])

    admin = InteractionAdmin()
    admin.session = mock_session  # type: ignore[attr-defined]
    # No engine set

    request = MagicMock()
    data = {"status": InteractionStatus.OK}

    with patch.object(
        InteractionAdmin.__bases__[0], "update_model", new_callable=AsyncMock
    ):
        # Should not raise exception even without engine
        await admin.update_model(request, str(interaction_id), data)

    assert mock_session.get.call_count == 2


@pytest.mark.asyncio
async def test_complaint_admin_update_model_no_engine() -> None:
    """Test ComplaintAdmin.update_model handles missing engine gracefully."""

    complaint_id = UUID("00000000-0000-0000-0000-000000000020")
    old_complaint = ComplaintModel(
        complaint_id=complaint_id,
        reporter_id=UUID("00000000-0000-0000-0000-000000000021"),
        reported_id=UUID("00000000-0000-0000-0000-000000000022"),
        order_id=UUID("00000000-0000-0000-0000-000000000023"),
        reason="Мошенничество",
        status=ComplaintStatus.PENDING,
        created_at=datetime.now(timezone.utc),
        reviewed_at=None,
    )
    new_complaint = ComplaintModel(
        complaint_id=complaint_id,
        reporter_id=old_complaint.reporter_id,
        reported_id=old_complaint.reported_id,
        order_id=old_complaint.order_id,
        reason=old_complaint.reason,
        status=ComplaintStatus.ACTION_TAKEN,
        created_at=old_complaint.created_at,
        reviewed_at=datetime.now(timezone.utc),
    )

    mock_session = MagicMock()
    mock_session.begin = MagicMock(return_value=AsyncContextManager())
    mock_session.get = AsyncMock(side_effect=[old_complaint, new_complaint])

    admin = ComplaintAdmin()
    admin.session = mock_session  # type: ignore[attr-defined]
    # No engine set

    request = MagicMock()
    data = {"status": ComplaintStatus.ACTION_TAKEN}

    with patch.object(
        ComplaintAdmin.__bases__[0], "update_model", new_callable=AsyncMock
    ):
        # Should not raise exception even without engine
        await admin.update_model(request, str(complaint_id), data)

    assert mock_session.get.call_count == 2


@pytest.mark.asyncio
async def test_complaint_admin_update_model_dismissed_exception() -> None:
    """Test ComplaintAdmin.update_model handles exception when dismissing complaint."""

    complaint_id = UUID("00000000-0000-0000-0000-000000000024")
    old_complaint = ComplaintModel(
        complaint_id=complaint_id,
        reporter_id=UUID("00000000-0000-0000-0000-000000000025"),
        reported_id=UUID("00000000-0000-0000-0000-000000000026"),
        order_id=UUID("00000000-0000-0000-0000-000000000027"),
        reason="Мошенничество",
        status=ComplaintStatus.PENDING,
        created_at=datetime.now(timezone.utc),
        reviewed_at=None,
    )
    new_complaint = ComplaintModel(
        complaint_id=complaint_id,
        reporter_id=old_complaint.reporter_id,
        reported_id=old_complaint.reported_id,
        order_id=old_complaint.order_id,
        reason=old_complaint.reason,
        status=ComplaintStatus.DISMISSED,
        created_at=old_complaint.created_at,
        reviewed_at=datetime.now(timezone.utc),
    )

    mock_session = MagicMock()
    mock_session.begin = MagicMock(return_value=AsyncContextManager())
    mock_session.get = AsyncMock(side_effect=[old_complaint, new_complaint])

    mock_engine = MagicMock()
    mock_engine.url = MagicMock()
    mock_engine.url.render_as_string = MagicMock(return_value="sqlite:///:memory:")

    admin = ComplaintAdmin()
    admin.session = mock_session  # type: ignore[attr-defined]
    admin._engine = mock_engine  # type: ignore[attr-defined]

    request = MagicMock()
    data = {"status": ComplaintStatus.DISMISSED}

    mock_complaint_service = MagicMock()
    mock_complaint_service.dismiss_complaint = MagicMock(
        side_effect=Exception("Service error")
    )

    with patch.object(
        ComplaintAdmin.__bases__[0], "update_model", new_callable=AsyncMock
    ), patch("ugc_bot.admin.app._get_services") as mock_get_services:
        mock_get_services.return_value = (None, mock_complaint_service, None)
        # Should not raise exception even if service fails
        await admin.update_model(request, str(complaint_id), data)

    assert mock_session.get.call_count == 2
    mock_complaint_service.dismiss_complaint.assert_called_once_with(complaint_id)
