"""Tests for admin app setup."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ugc_bot.admin.app import (
    ComplaintAdmin,
    EnumAwareAdmin,
    InteractionAdmin,
    OrderAdmin,
    UserAdmin,
    _get_order_moderation_deps,
    _get_services,
    create_admin_app,
)
from ugc_bot.application.services.offer_dispatch_service import (
    OfferDispatchService,
)
from ugc_bot.config import AppConfig
from ugc_bot.container import Container
from ugc_bot.domain.enums import (
    ComplaintStatus,
    InteractionStatus,
    OrderStatus,
    UserStatus,
)
from ugc_bot.infrastructure.db.models import (
    ComplaintModel,
    InteractionModel,
    OrderModel,
    UserModel,
)


def _make_session_maker_mock(mock_session: MagicMock) -> MagicMock:
    """Mock session_maker yielding mock_session as context manager."""

    mock_cm = AsyncMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_session)
    mock_cm.__aexit__ = AsyncMock(return_value=None)
    return MagicMock(return_value=mock_cm)


def _make_sync_session_maker_mock(mock_session: MagicMock) -> MagicMock:
    """Create a mock sync session_maker for is_async=False (production) path."""

    mock_cm = MagicMock()
    mock_cm.__enter__ = MagicMock(return_value=mock_session)
    mock_cm.__exit__ = MagicMock(return_value=None)
    return MagicMock(return_value=mock_cm)


def test_create_admin_app(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure admin app is created and mounted."""

    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "password")
    monkeypatch.setenv("ADMIN_SECRET", "secret")
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql+psycopg://user:pass@localhost/db"
    )

    startup_called: dict[str, object] = {}

    def _fake_startup_log(**kwargs):  # type: ignore[no-untyped-def]
        startup_called.update(kwargs)

    monkeypatch.setattr("ugc_bot.admin.app.log_startup_info", _fake_startup_log)

    app = create_admin_app()
    assert isinstance(app, FastAPI)
    assert any(getattr(route, "path", "") == "/admin" for route in app.routes)
    assert startup_called.get("service_name") == "admin"


def test_admin_health_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    """Health endpoint returns ok status."""

    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "password")
    monkeypatch.setenv("ADMIN_SECRET", "secret")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")

    app = create_admin_app()
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] in ("ok", "degraded")


def test_enum_aware_admin_edit_form_data_converts_enum_to_value() -> None:
    """_edit_form_data converts Enum to .value for correct select display."""
    from sqlalchemy import create_engine

    engine = create_engine("sqlite:///:memory:")
    app = FastAPI()
    admin = EnumAwareAdmin(app, engine, base_url="/admin")

    model = MagicMock()
    model.status = OrderStatus.PENDING_MODERATION
    model.order_type = "ugc_only"
    model.product_link = "https://example.com"

    model_view = MagicMock()
    model_view._form_prop_names = ["status", "order_type", "product_link"]

    result = admin._edit_form_data(model, model_view)

    assert result["status"] == "pending_moderation"
    assert result["order_type"] == "ugc_only"
    assert result["product_link"] == "https://example.com"


def test_create_admin_app_raises_when_admin_secret_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """create_admin_app raises ValueError when ADMIN_SECRET is empty."""
    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "password")
    monkeypatch.setenv("ADMIN_SECRET", "")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")

    with pytest.raises(ValueError, match="ADMIN_SECRET is required"):
        create_admin_app()


def test_create_admin_app_raises_when_admin_password_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """create_admin_app raises ValueError when ADMIN_PASSWORD is empty."""
    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "")
    monkeypatch.setenv("ADMIN_SECRET", "secret")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")

    with pytest.raises(ValueError, match="ADMIN_PASSWORD is required"):
        create_admin_app()


def test_admin_health_returns_degraded_when_db_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Health endpoint returns degraded when database connection fails."""
    monkeypatch.setenv("BOT_TOKEN", "token")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "password")
    monkeypatch.setenv("ADMIN_SECRET", "secret")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")

    mock_engine = MagicMock()
    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(side_effect=Exception("db fail"))
    mock_conn.__exit__ = MagicMock(return_value=None)
    mock_engine.connect.return_value = mock_conn

    with patch.object(Container, "get_admin_engine", return_value=mock_engine):
        app = create_admin_app()
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["db"] is False


def test_get_services() -> None:
    """Test _get_services function creates services correctly."""

    config = AppConfig.model_validate(
        {"BOT_TOKEN": "x", "DATABASE_URL": "sqlite:///:memory:"}
    )
    container = Container(config)
    user_service, complaint_service, interaction_service = _get_services(
        container
    )

    assert user_service is not None
    assert complaint_service is not None
    assert interaction_service is not None


def test_container_build_offer_dispatch_service() -> None:
    """Container.build_offer_dispatch_service returns OfferDispatchService."""

    config = AppConfig.model_validate(
        {"BOT_TOKEN": "x", "DATABASE_URL": "sqlite:///:memory:"}
    )
    container = Container(config)
    svc = container.build_offer_dispatch_service()
    assert isinstance(svc, OfferDispatchService)


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
    mock_session.get = AsyncMock(side_effect=[old_user, new_user])

    admin = UserAdmin()
    admin.session_maker = _make_session_maker_mock(mock_session)  # type: ignore[attr-defined]
    admin.is_async = True  # type: ignore[attr-defined]

    request = MagicMock()
    data = {"status": UserStatus.BLOCKED}

    with patch.object(
        UserAdmin.__bases__[0], "update_model", new_callable=AsyncMock
    ):
        await admin.update_model(request, str(user_id), data)

    assert mock_session.get.call_count == 2


@pytest.mark.asyncio
async def test_user_admin_update_model_exception_in_logging_suppressed() -> (
    None
):
    """When logging status change raises, update still succeeds."""
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
    mock_session.get = AsyncMock(side_effect=[old_user, new_user])

    mock_user_service = MagicMock()
    mock_user_service.get_user_by_id = AsyncMock(
        side_effect=RuntimeError("service fail")
    )

    mock_container = MagicMock()

    admin = UserAdmin()
    admin._container = mock_container  # type: ignore[attr-defined]
    admin.session_maker = _make_session_maker_mock(mock_session)  # type: ignore[attr-defined]
    admin.is_async = True  # type: ignore[attr-defined]

    request = MagicMock()
    data = {"status": UserStatus.BLOCKED}

    with (
        patch.object(
            UserAdmin.__bases__[0], "update_model", new_callable=AsyncMock
        ),
        patch(
            "ugc_bot.admin.app._get_services",
            return_value=(mock_user_service, None, None),
        ),
    ):
        result = await admin.update_model(request, str(user_id), data)

    assert result is not None
    mock_user_service.get_user_by_id.assert_called_once_with(user_id)


@pytest.mark.asyncio
async def test_user_admin_update_model_sync_session() -> None:
    """Test UserAdmin.update_model with sync session (production path)."""

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
    mock_session.get = MagicMock(side_effect=[old_user, new_user])

    admin = UserAdmin()
    admin.session_maker = _make_sync_session_maker_mock(mock_session)  # type: ignore[attr-defined]
    admin.is_async = False  # type: ignore[attr-defined]

    request = MagicMock()
    data = {"status": UserStatus.BLOCKED}

    with patch.object(
        UserAdmin.__bases__[0], "update_model", new_callable=AsyncMock
    ):
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
    mock_session.get = AsyncMock(side_effect=[old_interaction, new_interaction])

    mock_engine = MagicMock()
    mock_engine.url = MagicMock()
    mock_engine.url.render_as_string = MagicMock(
        return_value="sqlite:///:memory:"
    )

    admin = InteractionAdmin()
    admin.session_maker = _make_session_maker_mock(mock_session)  # type: ignore[attr-defined]
    admin.is_async = True  # type: ignore[attr-defined]
    admin._engine = mock_engine  # type: ignore[attr-defined]

    request = MagicMock()
    data = {"status": InteractionStatus.OK}

    mock_interaction_service = MagicMock()
    mock_interaction_service.manually_resolve_issue = AsyncMock()

    with (
        patch.object(
            InteractionAdmin.__bases__[0],
            "update_model",
            new_callable=AsyncMock,
        ),
        patch("ugc_bot.admin.app._get_services") as mock_get_services,
    ):
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
    mock_session.get = AsyncMock(side_effect=[old_interaction, new_interaction])

    mock_engine = MagicMock()
    mock_engine.url = MagicMock()
    mock_engine.url.render_as_string = MagicMock(
        return_value="sqlite:///:memory:"
    )

    admin = InteractionAdmin()
    admin.session_maker = _make_session_maker_mock(mock_session)  # type: ignore[attr-defined]
    admin.is_async = True  # type: ignore[attr-defined]
    admin._engine = mock_engine  # type: ignore[attr-defined]

    request = MagicMock()
    data = {"status": InteractionStatus.NO_DEAL}

    mock_interaction_service = MagicMock()
    mock_interaction_service.manually_resolve_issue = AsyncMock()

    with (
        patch.object(
            InteractionAdmin.__bases__[0],
            "update_model",
            new_callable=AsyncMock,
        ),
        patch("ugc_bot.admin.app._get_services") as mock_get_services,
    ):
        mock_get_services.return_value = (None, None, mock_interaction_service)
        await admin.update_model(request, str(interaction_id), data)

    assert mock_session.get.call_count == 2
    mock_interaction_service.manually_resolve_issue.assert_called_once_with(
        interaction_id, InteractionStatus.NO_DEAL
    )


@pytest.mark.asyncio
async def test_complaint_admin_update_model_action_taken() -> None:
    """Test ComplaintAdmin.update_model blocks user on ACTION_TAKEN."""

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
    mock_session.get = AsyncMock(side_effect=[old_complaint, new_complaint])

    mock_engine = MagicMock()
    mock_engine.url = MagicMock()
    mock_engine.url.render_as_string = MagicMock(
        return_value="sqlite:///:memory:"
    )

    admin = ComplaintAdmin()
    admin.session_maker = _make_session_maker_mock(mock_session)  # type: ignore[attr-defined]
    admin.is_async = True  # type: ignore[attr-defined]
    admin._engine = mock_engine  # type: ignore[attr-defined]

    request = MagicMock()
    data = {"status": ComplaintStatus.ACTION_TAKEN}

    mock_user_service = MagicMock()
    mock_user_service.update_status = AsyncMock()
    mock_complaint_service = MagicMock()
    mock_complaint_service.resolve_complaint_with_action = AsyncMock()

    with (
        patch.object(
            ComplaintAdmin.__bases__[0], "update_model", new_callable=AsyncMock
        ),
        patch("ugc_bot.admin.app._get_services") as mock_get_services,
    ):
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
    """Test ComplaintAdmin.update_model dismisses complaint on DISMISSED."""

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
    mock_session.get = AsyncMock(side_effect=[old_complaint, new_complaint])

    mock_engine = MagicMock()
    mock_engine.url = MagicMock()
    mock_engine.url.render_as_string = MagicMock(
        return_value="sqlite:///:memory:"
    )

    admin = ComplaintAdmin()
    admin.session_maker = _make_session_maker_mock(mock_session)  # type: ignore[attr-defined]
    admin.is_async = True  # type: ignore[attr-defined]
    admin._engine = mock_engine  # type: ignore[attr-defined]

    request = MagicMock()
    data = {"status": ComplaintStatus.DISMISSED}

    mock_complaint_service = MagicMock()
    mock_complaint_service.dismiss_complaint = AsyncMock()

    with (
        patch.object(
            ComplaintAdmin.__bases__[0], "update_model", new_callable=AsyncMock
        ),
        patch("ugc_bot.admin.app._get_services") as mock_get_services,
    ):
        mock_get_services.return_value = (None, mock_complaint_service, None)
        await admin.update_model(request, str(complaint_id), data)

    assert mock_session.get.call_count == 2
    mock_complaint_service.dismiss_complaint.assert_called_once_with(
        complaint_id
    )


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
    mock_session.get = AsyncMock(side_effect=[old_interaction, new_interaction])

    admin = InteractionAdmin()
    admin.session_maker = _make_session_maker_mock(mock_session)  # type: ignore[attr-defined]
    admin.is_async = True  # type: ignore[attr-defined]
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
    mock_session.get = AsyncMock(side_effect=[old_complaint, new_complaint])

    admin = ComplaintAdmin()
    admin.session_maker = _make_session_maker_mock(mock_session)  # type: ignore[attr-defined]
    admin.is_async = True  # type: ignore[attr-defined]
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
    """Test ComplaintAdmin.update_model handles exception on dismiss."""

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
    mock_session.get = AsyncMock(side_effect=[old_complaint, new_complaint])

    mock_engine = MagicMock()
    mock_engine.url = MagicMock()
    mock_engine.url.render_as_string = MagicMock(
        return_value="sqlite:///:memory:"
    )

    admin = ComplaintAdmin()
    admin.session_maker = _make_session_maker_mock(mock_session)  # type: ignore[attr-defined]
    admin.is_async = True  # type: ignore[attr-defined]
    admin._engine = mock_engine  # type: ignore[attr-defined]

    request = MagicMock()
    data = {"status": ComplaintStatus.DISMISSED}

    mock_complaint_service = MagicMock()
    mock_complaint_service.dismiss_complaint = MagicMock(
        side_effect=Exception("Service error")
    )

    with (
        patch.object(
            ComplaintAdmin.__bases__[0], "update_model", new_callable=AsyncMock
        ),
        patch("ugc_bot.admin.app._get_services") as mock_get_services,
    ):
        mock_get_services.return_value = (None, mock_complaint_service, None)
        # Should not raise exception even if service fails
        await admin.update_model(request, str(complaint_id), data)

    assert mock_session.get.call_count == 2
    mock_complaint_service.dismiss_complaint.assert_called_once_with(
        complaint_id
    )


def test_get_order_moderation_deps() -> None:
    """Test _get_order_moderation_deps function creates services correctly."""
    from unittest.mock import patch

    config = AppConfig.model_validate(
        {"BOT_TOKEN": "x", "DATABASE_URL": "sqlite:///:memory:"}
    )
    container = Container(config)

    mock_outbox_publisher = MagicMock()
    mock_order_repo = MagicMock()

    with (
        patch.object(
            container,
            "build_outbox_deps",
            return_value=(mock_outbox_publisher, None),
        ),
        patch.object(
            container,
            "build_repos",
            return_value={"order_repo": mock_order_repo},
        ),
    ):
        content_moderation, outbox_publisher, order_repo = (
            _get_order_moderation_deps(container)
        )

    assert content_moderation is not None
    assert outbox_publisher is not None
    assert order_repo is not None


@pytest.mark.asyncio
async def test_user_admin_update_model_user_not_found() -> None:
    """Test UserAdmin.update_model handles user not found gracefully."""
    user_id = UUID("00000000-0000-0000-0000-000000000030")
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
    mock_session.get = AsyncMock(side_effect=[old_user, new_user])

    mock_user_service = MagicMock()
    mock_user_service.get_user_by_id = AsyncMock(return_value=None)

    mock_container = MagicMock()

    admin = UserAdmin()
    admin._container = mock_container  # type: ignore[attr-defined]
    admin.session_maker = _make_session_maker_mock(mock_session)  # type: ignore[attr-defined]
    admin.is_async = True  # type: ignore[attr-defined]

    request = MagicMock()
    data = {"status": UserStatus.BLOCKED}

    with (
        patch.object(
            UserAdmin.__bases__[0], "update_model", new_callable=AsyncMock
        ),
        patch(
            "ugc_bot.admin.app._get_services",
            return_value=(mock_user_service, None, None),
        ),
    ):
        result = await admin.update_model(request, str(user_id), data)

    assert result is not None
    mock_user_service.get_user_by_id.assert_called_once_with(user_id)


@pytest.mark.asyncio
async def test_order_admin_update_model_banned_content_rejected() -> None:
    """Test OrderAdmin.update_model rejects order with banned content."""
    order_id = UUID("00000000-0000-0000-0000-000000000040")
    old_order = OrderModel(
        order_id=order_id,
        advertiser_id=UUID("00000000-0000-0000-0000-000000000041"),
        order_type="ugc_only",
        product_link="https://1xbet.com/link",
        offer_text="Test",
        price=100.0,
        bloggers_needed=1,
        status=OrderStatus.PENDING_MODERATION,
        created_at=datetime.now(timezone.utc),
    )

    mock_session = MagicMock()
    mock_session.get = AsyncMock(return_value=old_order)

    mock_container = MagicMock()
    mock_container.build_outbox_deps = MagicMock(return_value=(None, None))
    mock_container.build_repos = MagicMock(
        return_value={"order_repo": MagicMock()}
    )

    admin = OrderAdmin()
    admin._container = mock_container  # type: ignore[attr-defined]
    admin.session_maker = _make_session_maker_mock(mock_session)  # type: ignore[attr-defined]
    admin.is_async = True  # type: ignore[attr-defined]

    request = MagicMock()
    data = {
        "status": OrderStatus.ACTIVE,
        "product_link": "https://1xbet.com/link",
        "offer_text": "Test",
    }

    with (
        patch.object(
            OrderAdmin.__bases__[0], "update_model", new_callable=AsyncMock
        ),
        pytest.raises(ValueError, match="Запрещённый контент"),
    ):
        await admin.update_model(request, str(order_id), data)


@pytest.mark.asyncio
async def test_order_admin_update_model_activation_publishes() -> None:
    """Test OrderAdmin.update_model publishes activation on status change."""
    from contextlib import asynccontextmanager

    order_id = UUID("00000000-0000-0000-0000-000000000050")
    old_order = OrderModel(
        order_id=order_id,
        advertiser_id=UUID("00000000-0000-0000-0000-000000000051"),
        order_type="ugc_only",
        product_link="https://example.com/product",
        offer_text="Test",
        price=100.0,
        bloggers_needed=1,
        status=OrderStatus.PENDING_MODERATION,
        created_at=datetime.now(timezone.utc),
    )
    new_order = OrderModel(
        order_id=order_id,
        advertiser_id=old_order.advertiser_id,
        order_type=old_order.order_type,
        product_link=old_order.product_link,
        offer_text=old_order.offer_text,
        price=old_order.price,
        bloggers_needed=old_order.bloggers_needed,
        status=OrderStatus.ACTIVE,
        created_at=old_order.created_at,
    )

    mock_session = MagicMock()
    mock_session.get = AsyncMock(side_effect=[old_order, new_order])

    mock_order = MagicMock()
    mock_order_repo = MagicMock()
    mock_order_repo.get_by_id = AsyncMock(return_value=mock_order)

    mock_outbox_publisher = MagicMock()
    mock_outbox_publisher.publish_order_activation = AsyncMock()

    @asynccontextmanager
    async def _tx():
        yield mock_session

    mock_tm = MagicMock()
    mock_tm.transaction = MagicMock(return_value=_tx())

    mock_container = MagicMock()
    mock_container.build_outbox_deps = MagicMock(
        return_value=(mock_outbox_publisher, None)
    )
    mock_container.build_repos = MagicMock(
        return_value={"order_repo": mock_order_repo}
    )
    mock_container.transaction_manager = mock_tm

    admin = OrderAdmin()
    admin._container = mock_container  # type: ignore[attr-defined]
    admin.session_maker = _make_session_maker_mock(mock_session)  # type: ignore[attr-defined]
    admin.is_async = True  # type: ignore[attr-defined]

    request = MagicMock()
    data = {"status": OrderStatus.ACTIVE}

    with patch.object(
        OrderAdmin.__bases__[0], "update_model", new_callable=AsyncMock
    ):
        await admin.update_model(request, str(order_id), data)

    assert mock_session.get.call_count == 2
    mock_order_repo.get_by_id.assert_called_once_with(
        order_id, session=mock_session
    )
    mock_outbox_publisher.publish_order_activation.assert_called_once_with(
        mock_order, session=mock_session
    )


@pytest.mark.asyncio
async def test_order_admin_update_model_activation_no_order() -> None:
    """Test OrderAdmin.update_model handles missing order gracefully."""
    from contextlib import asynccontextmanager

    order_id = UUID("00000000-0000-0000-0000-000000000060")
    old_order = OrderModel(
        order_id=order_id,
        advertiser_id=UUID("00000000-0000-0000-0000-000000000061"),
        order_type="ugc_only",
        product_link="https://example.com/product",
        offer_text="Test",
        price=100.0,
        bloggers_needed=1,
        status=OrderStatus.PENDING_MODERATION,
        created_at=datetime.now(timezone.utc),
    )
    new_order = OrderModel(
        order_id=order_id,
        advertiser_id=old_order.advertiser_id,
        order_type=old_order.order_type,
        product_link=old_order.product_link,
        offer_text=old_order.offer_text,
        price=old_order.price,
        bloggers_needed=old_order.bloggers_needed,
        status=OrderStatus.ACTIVE,
        created_at=old_order.created_at,
    )

    mock_session = MagicMock()
    mock_session.get = AsyncMock(side_effect=[old_order, new_order])

    mock_order_repo = MagicMock()
    mock_order_repo.get_by_id = AsyncMock(return_value=None)

    mock_outbox_publisher = MagicMock()
    mock_outbox_publisher.publish_order_activation = AsyncMock()

    @asynccontextmanager
    async def _tx():
        yield mock_session

    mock_tm = MagicMock()
    mock_tm.transaction = MagicMock(return_value=_tx())

    mock_container = MagicMock()
    mock_container.build_outbox_deps = MagicMock(
        return_value=(mock_outbox_publisher, None)
    )
    mock_container.build_repos = MagicMock(
        return_value={"order_repo": mock_order_repo}
    )
    mock_container.transaction_manager = mock_tm

    admin = OrderAdmin()
    admin._container = mock_container  # type: ignore[attr-defined]
    admin.session_maker = _make_session_maker_mock(mock_session)  # type: ignore[attr-defined]
    admin.is_async = True  # type: ignore[attr-defined]

    request = MagicMock()
    data = {"status": OrderStatus.ACTIVE}

    with patch.object(
        OrderAdmin.__bases__[0], "update_model", new_callable=AsyncMock
    ):
        await admin.update_model(request, str(order_id), data)

    assert mock_session.get.call_count == 2
    mock_order_repo.get_by_id.assert_called_once_with(
        order_id, session=mock_session
    )
    mock_outbox_publisher.publish_order_activation.assert_not_called()


@pytest.mark.asyncio
async def test_order_admin_update_model_activation_exception_handled() -> None:
    """Test OrderAdmin.update_model handles exception during publishing."""
    from contextlib import asynccontextmanager

    order_id = UUID("00000000-0000-0000-0000-000000000070")
    old_order = OrderModel(
        order_id=order_id,
        advertiser_id=UUID("00000000-0000-0000-0000-000000000071"),
        order_type="ugc_only",
        product_link="https://example.com/product",
        offer_text="Test",
        price=100.0,
        bloggers_needed=1,
        status=OrderStatus.PENDING_MODERATION,
        created_at=datetime.now(timezone.utc),
    )
    new_order = OrderModel(
        order_id=order_id,
        advertiser_id=old_order.advertiser_id,
        order_type=old_order.order_type,
        product_link=old_order.product_link,
        offer_text=old_order.offer_text,
        price=old_order.price,
        bloggers_needed=old_order.bloggers_needed,
        status=OrderStatus.ACTIVE,
        created_at=old_order.created_at,
    )

    mock_session = MagicMock()
    mock_session.get = AsyncMock(side_effect=[old_order, new_order])

    mock_order = MagicMock()
    mock_order_repo = MagicMock()
    mock_order_repo.get_by_id = AsyncMock(return_value=mock_order)

    mock_outbox_publisher = MagicMock()
    mock_outbox_publisher.publish_order_activation = AsyncMock(
        side_effect=Exception("Publish failed")
    )

    @asynccontextmanager
    async def _tx():
        yield mock_session

    mock_tm = MagicMock()
    mock_tm.transaction = MagicMock(return_value=_tx())

    mock_container = MagicMock()
    mock_container.build_outbox_deps = MagicMock(
        return_value=(mock_outbox_publisher, None)
    )
    mock_container.build_repos = MagicMock(
        return_value={"order_repo": mock_order_repo}
    )
    mock_container.transaction_manager = mock_tm

    admin = OrderAdmin()
    admin._container = mock_container  # type: ignore[attr-defined]
    admin.session_maker = _make_session_maker_mock(mock_session)  # type: ignore[attr-defined]
    admin.is_async = True  # type: ignore[attr-defined]

    request = MagicMock()
    data = {"status": OrderStatus.ACTIVE}

    with patch.object(
        OrderAdmin.__bases__[0], "update_model", new_callable=AsyncMock
    ):
        # Should not raise exception
        result = await admin.update_model(request, str(order_id), data)

    assert result is not None
    mock_outbox_publisher.publish_order_activation.assert_called_once()


def test_enum_aware_admin_edit_form_data_skip_existing() -> None:
    """_edit_form_data skips properties already in data."""
    from sqlalchemy import create_engine

    engine = create_engine("sqlite:///:memory:")
    app = FastAPI()
    admin = EnumAwareAdmin(app, engine, base_url="/admin")

    model = MagicMock()
    model.status = OrderStatus.PENDING_MODERATION

    model_view = MagicMock()
    model_view._form_prop_names = ["status"]

    # Simulate data already containing status
    admin._normalize_wtform_data = MagicMock(
        return_value={"status": "pending_moderation"}
    )

    result = admin._edit_form_data(model, model_view)

    assert result["status"] == "pending_moderation"


def test_enum_aware_admin_edit_form_data_handles_attribute_error() -> None:
    """_edit_form_data handles exception when getting attribute."""
    from sqlalchemy import create_engine

    engine = create_engine("sqlite:///:memory:")
    app = FastAPI()
    admin = EnumAwareAdmin(app, engine, base_url="/admin")

    model = MagicMock()
    # Make getattr raise exception
    model.__getattribute__ = MagicMock(side_effect=AttributeError("No attr"))

    model_view = MagicMock()
    model_view._form_prop_names = ["nonexistent"]

    admin._normalize_wtform_data = MagicMock(return_value={})

    # Should not raise exception
    result = admin._edit_form_data(model, model_view)

    assert isinstance(result, dict)
