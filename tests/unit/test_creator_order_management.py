"""Unit tests for manager creator order management feature."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ugc_bot.application.services.interaction_service import InteractionService
from ugc_bot.domain.entities import OfferDispatch, Order, User
from ugc_bot.domain.enums import (
    InteractionStatus,
    MessengerType,
    OrderStatus,
    OrderType,
    UserStatus,
)
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryInteractionRepository,
    InMemoryOfferDispatchRepository,
)
from ugc_bot.miniapp.api import router as miniapp_router

ORDER_ID = UUID("00000000-0000-0000-0000-000000000d00")
BLOGGER_ID = UUID("00000000-0000-0000-0000-000000000d01")
ADV_ID = UUID("00000000-0000-0000-0000-000000000d02")
MGR_ID = UUID("00000000-0000-0000-0000-000000000d03")


# ---------------------------------------------------------------------------
# InMemoryOfferDispatchRepository.set_in_offer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_in_offer_updates_value() -> None:
    """set_in_offer updates the in_offer flag to False."""
    repo = InMemoryOfferDispatchRepository()
    await repo.record_sent(ORDER_ID, BLOGGER_ID)
    await repo.set_in_offer(ORDER_ID, BLOGGER_ID, False)
    result = await repo.get_by_order_and_blogger(ORDER_ID, BLOGGER_ID)
    assert result is not None
    assert result.in_offer is False


@pytest.mark.asyncio
async def test_set_in_offer_can_set_true() -> None:
    """set_in_offer can also set in_offer back to True."""
    repo = InMemoryOfferDispatchRepository()
    await repo.record_sent(ORDER_ID, BLOGGER_ID)
    await repo.set_in_offer(ORDER_ID, BLOGGER_ID, False)
    await repo.set_in_offer(ORDER_ID, BLOGGER_ID, True)
    result = await repo.get_by_order_and_blogger(ORDER_ID, BLOGGER_ID)
    assert result is not None
    assert result.in_offer is True


@pytest.mark.asyncio
async def test_set_in_offer_noop_when_missing() -> None:
    """set_in_offer does not raise if dispatch does not exist."""
    repo = InMemoryOfferDispatchRepository()
    await repo.set_in_offer(ORDER_ID, BLOGGER_ID, False)  # no exception
    result = await repo.get_by_order_and_blogger(ORDER_ID, BLOGGER_ID)
    assert result is None


# ---------------------------------------------------------------------------
# InteractionService.cancel_interaction
# ---------------------------------------------------------------------------


def _make_interaction_service() -> InteractionService:
    """Create InteractionService with InMemory repos."""
    return InteractionService(
        interaction_repo=InMemoryInteractionRepository(),
        transaction_manager=None,
        postpone_delay_minutes=60,
        max_postpone_count=3,
        metrics_collector=None,
        referral_income_service=None,
    )


@pytest.mark.asyncio
async def test_cancel_interaction_sets_deleted() -> None:
    """cancel_interaction sets PENDING interaction to DELETED."""
    service = _make_interaction_service()
    await service.create_for_contacts_sent(ORDER_ID, BLOGGER_ID, ADV_ID)
    await service.cancel_interaction(ORDER_ID, BLOGGER_ID, ADV_ID)
    interaction = await service._get_by_participants(
        ORDER_ID, BLOGGER_ID, ADV_ID
    )
    assert interaction is not None
    assert interaction.status == InteractionStatus.DELETED


@pytest.mark.asyncio
async def test_cancel_interaction_noop_when_already_deleted() -> None:
    """cancel_interaction is no-op if interaction already DELETED."""
    service = _make_interaction_service()
    await service.create_for_contacts_sent(ORDER_ID, BLOGGER_ID, ADV_ID)
    await service.cancel_interaction(ORDER_ID, BLOGGER_ID, ADV_ID)
    await service.cancel_interaction(
        ORDER_ID, BLOGGER_ID, ADV_ID
    )  # second call
    interaction = await service._get_by_participants(
        ORDER_ID, BLOGGER_ID, ADV_ID
    )
    assert interaction is not None
    assert interaction.status == InteractionStatus.DELETED


@pytest.mark.asyncio
async def test_cancel_interaction_noop_when_not_found() -> None:
    """cancel_interaction is no-op when no interaction exists."""
    service = _make_interaction_service()
    await service.cancel_interaction(
        ORDER_ID, BLOGGER_ID, ADV_ID
    )  # no exception


# ---------------------------------------------------------------------------
# API endpoint helpers
# ---------------------------------------------------------------------------


def _make_test_user(
    user_id: UUID, telegram_id: str = "11111", **kwargs
) -> User:
    return User(
        user_id=user_id,
        telegram_id=telegram_id,
        messenger_type=MessengerType.TELEGRAM,
        username="user",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        **kwargs,
    )


def _make_dispatch(
    order_id: UUID,
    blogger_id: UUID,
    in_offer: bool = True,
    manager_id: UUID | None = None,
) -> OfferDispatch:
    return OfferDispatch(
        order_id=order_id,
        blogger_id=blogger_id,
        created_at=datetime.now(timezone.utc),
        in_offer=in_offer,
        manager_id=manager_id,
    )


def _make_order(
    order_id: UUID, advertiser_id: UUID, bloggers_needed: int = 3
) -> Order:
    return Order(
        order_id=order_id,
        advertiser_id=advertiser_id,
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Test",
        barter_description=None,
        price=100.0,
        bloggers_needed=bloggers_needed,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )


def _build_dispatcher(
    *,
    is_manager: bool = True,
    dispatch: OfferDispatch | None = None,
    order: Order | None = None,
    in_offer_count: int = 1,
) -> dict:
    return {
        "manager_service": MagicMock(
            is_manager_for_order=AsyncMock(return_value=is_manager)
        ),
        "offer_dispatch_repo": MagicMock(
            get_by_order_and_blogger=AsyncMock(return_value=dispatch),
            set_in_offer=AsyncMock(),
            set_manager=AsyncMock(),
            count_accepted_by_order=AsyncMock(return_value=in_offer_count),
        ),
        "order_repo": MagicMock(get_by_id=AsyncMock(return_value=order)),
        "user_repo": MagicMock(get_by_id=AsyncMock(return_value=None)),
        "interaction_service": MagicMock(
            cancel_interaction=AsyncMock(),
            reactivate_or_create_for_contacts_sent=AsyncMock(),
            get_or_create=AsyncMock(
                return_value=MagicMock(interaction_id=uuid4())
            ),
        ),
        "messenger_client": MagicMock(),
        "bot_texts_service": MagicMock(
            get=AsyncMock(return_value="notification text")
        ),
    }


def _app(dispatcher: dict) -> FastAPI:
    app = FastAPI()
    app.include_router(miniapp_router)
    app.state.dispatcher = dispatcher
    return app


# ---------------------------------------------------------------------------
# POST /manager/orders/{order_id}/creators/{blogger_id}/remove
# ---------------------------------------------------------------------------


class TestManagerRemoveCreatorEndpoint:
    _ORDER_ID = UUID("00000000-0000-0000-0000-000000000e00")
    _BLOGGER_ID = UUID("00000000-0000-0000-0000-000000000e01")
    _ADV_ID = UUID("00000000-0000-0000-0000-000000000e02")

    def test_remove_returns_ok(self) -> None:
        dispatch = _make_dispatch(
            self._ORDER_ID, self._BLOGGER_ID, in_offer=True
        )
        order = _make_order(self._ORDER_ID, self._ADV_ID)
        dispatcher = _build_dispatcher(dispatch=dispatch, order=order)

        with (
            patch(
                "ugc_bot.miniapp.api._ensure_user_and_get_id",
                AsyncMock(return_value=self._ORDER_ID),
            ),
            TestClient(_app(dispatcher)) as client,
        ):
            resp = client.post(
                f"/api/manager/orders/{self._ORDER_ID}/creators/{self._BLOGGER_ID}/remove",
                json={"init_data": "test"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "interaction_id" in data
        dispatcher["offer_dispatch_repo"].set_in_offer.assert_awaited_once_with(
            self._ORDER_ID, self._BLOGGER_ID, False
        )
        dispatcher[
            "interaction_service"
        ].cancel_interaction.assert_not_awaited()

    def test_remove_409_already_in_reserve(self) -> None:
        dispatch = _make_dispatch(
            self._ORDER_ID, self._BLOGGER_ID, in_offer=False
        )
        order = _make_order(self._ORDER_ID, self._ADV_ID)
        dispatcher = _build_dispatcher(dispatch=dispatch, order=order)

        with (
            patch(
                "ugc_bot.miniapp.api._ensure_user_and_get_id",
                AsyncMock(return_value=self._ORDER_ID),
            ),
            TestClient(_app(dispatcher)) as client,
        ):
            resp = client.post(
                f"/api/manager/orders/{self._ORDER_ID}/creators/{self._BLOGGER_ID}/remove",
                json={"init_data": "test"},
            )
        assert resp.status_code == 409

    def test_remove_404_dispatch_missing(self) -> None:
        order = _make_order(self._ORDER_ID, self._ADV_ID)
        dispatcher = _build_dispatcher(dispatch=None, order=order)

        with (
            patch(
                "ugc_bot.miniapp.api._ensure_user_and_get_id",
                AsyncMock(return_value=self._ORDER_ID),
            ),
            TestClient(_app(dispatcher)) as client,
        ):
            resp = client.post(
                f"/api/manager/orders/{self._ORDER_ID}/creators/{self._BLOGGER_ID}/remove",
                json={"init_data": "test"},
            )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /manager/orders/{order_id}/creators/{blogger_id}/add
# ---------------------------------------------------------------------------


class TestManagerAddCreatorEndpoint:
    _ORDER_ID = UUID("00000000-0000-0000-0000-000000000f00")
    _BLOGGER_ID = UUID("00000000-0000-0000-0000-000000000f01")
    _ADV_ID = UUID("00000000-0000-0000-0000-000000000f02")

    def test_add_returns_ok(self) -> None:
        dispatch = _make_dispatch(
            self._ORDER_ID, self._BLOGGER_ID, in_offer=False
        )
        order = _make_order(self._ORDER_ID, self._ADV_ID, bloggers_needed=3)
        dispatcher = _build_dispatcher(
            dispatch=dispatch, order=order, in_offer_count=1
        )

        with (
            patch(
                "ugc_bot.miniapp.api._ensure_user_and_get_id",
                AsyncMock(return_value=self._ORDER_ID),
            ),
            TestClient(_app(dispatcher)) as client,
        ):
            resp = client.post(
                f"/api/manager/orders/{self._ORDER_ID}/creators/{self._BLOGGER_ID}/add",
                json={"init_data": "test"},
            )
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        dispatcher["offer_dispatch_repo"].set_in_offer.assert_awaited_once_with(
            self._ORDER_ID, self._BLOGGER_ID, True
        )
        dispatcher["offer_dispatch_repo"].set_manager.assert_awaited_once_with(
            self._ORDER_ID, self._BLOGGER_ID, self._ORDER_ID
        )
        dispatcher[
            "interaction_service"
        ].reactivate_or_create_for_contacts_sent.assert_awaited_once()

    def test_add_409_no_free_slots(self) -> None:
        dispatch = _make_dispatch(
            self._ORDER_ID, self._BLOGGER_ID, in_offer=False
        )
        order = _make_order(self._ORDER_ID, self._ADV_ID, bloggers_needed=2)
        dispatcher = _build_dispatcher(
            dispatch=dispatch, order=order, in_offer_count=2
        )

        with (
            patch(
                "ugc_bot.miniapp.api._ensure_user_and_get_id",
                AsyncMock(return_value=self._ORDER_ID),
            ),
            TestClient(_app(dispatcher)) as client,
        ):
            resp = client.post(
                f"/api/manager/orders/{self._ORDER_ID}/creators/{self._BLOGGER_ID}/add",
                json={"init_data": "test"},
            )
        assert resp.status_code == 409

    def test_add_409_already_in_order(self) -> None:
        dispatch = _make_dispatch(
            self._ORDER_ID, self._BLOGGER_ID, in_offer=True
        )
        order = _make_order(self._ORDER_ID, self._ADV_ID)
        dispatcher = _build_dispatcher(
            dispatch=dispatch, order=order, in_offer_count=1
        )

        with (
            patch(
                "ugc_bot.miniapp.api._ensure_user_and_get_id",
                AsyncMock(return_value=self._ORDER_ID),
            ),
            TestClient(_app(dispatcher)) as client,
        ):
            resp = client.post(
                f"/api/manager/orders/{self._ORDER_ID}/creators/{self._BLOGGER_ID}/add",
                json={"init_data": "test"},
            )
        assert resp.status_code == 409

    def test_add_notifies_creator_with_manager_telegram(self) -> None:
        """Notification sent when creator found; manager_telegram included."""
        creator = _make_test_user(
            self._BLOGGER_ID, telegram_id="999", language="ru"
        )
        manager = _make_test_user(MGR_ID, telegram_id="888", telegram="mgr_tg")
        dispatch = _make_dispatch(
            self._ORDER_ID,
            self._BLOGGER_ID,
            in_offer=False,
            manager_id=MGR_ID,
        )
        order = _make_order(self._ORDER_ID, self._ADV_ID, bloggers_needed=3)

        dispatcher = _build_dispatcher(
            dispatch=dispatch, order=order, in_offer_count=1
        )
        dispatcher["user_repo"].get_by_id = AsyncMock(
            side_effect=lambda uid: (
                creator if uid == self._BLOGGER_ID else manager
            )
        )
        dispatcher["bot_texts_service"].get = AsyncMock(
            return_value="Добавлены в заказ! Менеджер: {manager_telegram}."
        )

        with (
            patch(
                "ugc_bot.miniapp.api._ensure_user_and_get_id",
                AsyncMock(return_value=self._ORDER_ID),
            ),
            patch("ugc_bot.miniapp.api.send_with_retry", new=AsyncMock()),
            TestClient(_app(dispatcher)) as client,
        ):
            resp = client.post(
                f"/api/manager/orders/{self._ORDER_ID}/creators/{self._BLOGGER_ID}/add",
                json={"init_data": "test"},
            )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Coverage: creator notification branch for /remove
# ---------------------------------------------------------------------------


class TestManagerRemoveNotification:
    _ORDER_ID = UUID("00000000-0000-0000-0000-000000000a00")
    _BLOGGER_ID = UUID("00000000-0000-0000-0000-000000000a01")
    _ADV_ID = UUID("00000000-0000-0000-0000-000000000a02")

    def test_remove_notifies_creator_when_found(self) -> None:
        """Notification is sent when creator User is found."""
        creator = _make_test_user(
            self._BLOGGER_ID, telegram_id="777", language="ru"
        )
        dispatch = _make_dispatch(
            self._ORDER_ID, self._BLOGGER_ID, in_offer=True
        )
        order = _make_order(self._ORDER_ID, self._ADV_ID)
        dispatcher = _build_dispatcher(dispatch=dispatch, order=order)
        dispatcher["user_repo"].get_by_id = AsyncMock(return_value=creator)

        with (
            patch(
                "ugc_bot.miniapp.api._ensure_user_and_get_id",
                AsyncMock(return_value=self._ORDER_ID),
            ),
            patch("ugc_bot.miniapp.api.send_with_retry", new=AsyncMock()),
            TestClient(_app(dispatcher)) as client,
        ):
            resp = client.post(
                f"/api/manager/orders/{self._ORDER_ID}/creators/{self._BLOGGER_ID}/remove",
                json={"init_data": "test"},
            )
        assert resp.status_code == 200

    def test_remove_403_not_manager(self) -> None:
        dispatcher = _build_dispatcher(is_manager=False)

        with (
            patch(
                "ugc_bot.miniapp.api._ensure_user_and_get_id",
                AsyncMock(return_value=self._ORDER_ID),
            ),
            TestClient(_app(dispatcher)) as client,
        ):
            resp = client.post(
                f"/api/manager/orders/{self._ORDER_ID}/creators/{self._BLOGGER_ID}/remove",
                json={"init_data": "test"},
            )
        assert resp.status_code == 403

    def test_add_403_not_manager(self) -> None:
        dispatcher = _build_dispatcher(is_manager=False)

        with (
            patch(
                "ugc_bot.miniapp.api._ensure_user_and_get_id",
                AsyncMock(return_value=self._ORDER_ID),
            ),
            TestClient(_app(dispatcher)) as client,
        ):
            resp = client.post(
                f"/api/manager/orders/{self._ORDER_ID}/creators/{self._BLOGGER_ID}/add",
                json={"init_data": "test"},
            )
        assert resp.status_code == 403

    def test_remove_404_order_not_found(self) -> None:
        dispatcher = _build_dispatcher(order=None)

        with (
            patch(
                "ugc_bot.miniapp.api._ensure_user_and_get_id",
                AsyncMock(return_value=self._ORDER_ID),
            ),
            TestClient(_app(dispatcher)) as client,
        ):
            resp = client.post(
                f"/api/manager/orders/{self._ORDER_ID}/creators/{self._BLOGGER_ID}/remove",
                json={"init_data": "test"},
            )
        assert resp.status_code == 404

    def test_add_404_order_not_found(self) -> None:
        dispatcher = _build_dispatcher(order=None)

        with (
            patch(
                "ugc_bot.miniapp.api._ensure_user_and_get_id",
                AsyncMock(return_value=self._ORDER_ID),
            ),
            TestClient(_app(dispatcher)) as client,
        ):
            resp = client.post(
                f"/api/manager/orders/{self._ORDER_ID}/creators/{self._BLOGGER_ID}/add",
                json={"init_data": "test"},
            )
        assert resp.status_code == 404

    def test_add_404_dispatch_missing(self) -> None:
        order = _make_order(self._ORDER_ID, self._ADV_ID)
        dispatcher = _build_dispatcher(dispatch=None, order=order)

        with (
            patch(
                "ugc_bot.miniapp.api._ensure_user_and_get_id",
                AsyncMock(return_value=self._ORDER_ID),
            ),
            TestClient(_app(dispatcher)) as client,
        ):
            resp = client.post(
                f"/api/manager/orders/{self._ORDER_ID}/creators/{self._BLOGGER_ID}/add",
                json={"init_data": "test"},
            )
        assert resp.status_code == 404
