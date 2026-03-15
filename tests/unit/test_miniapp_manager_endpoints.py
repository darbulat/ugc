"""Tests for miniapp manager endpoints."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from ugc_bot.domain.entities import OfferDispatch, Order
from ugc_bot.domain.enums import OrderStatus, OrderType
from ugc_bot.miniapp.api import (
    ManagerCreatorsRequest,
    ManagerOrdersRequest,
    manager_creators,
    manager_orders,
)

ORDER_ID = UUID("00000000-0000-0000-0000-000000000b01")
MANAGER_ID = UUID("00000000-0000-0000-0000-000000000b10")
BLOGGER_ID = UUID("00000000-0000-0000-0000-000000000b20")


def _make_order() -> Order:
    return Order(
        order_id=ORDER_ID,
        advertiser_id=uuid4(),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=3,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
    )


def _make_dispatch() -> OfferDispatch:
    return OfferDispatch(
        order_id=ORDER_ID,
        blogger_id=BLOGGER_ID,
        created_at=datetime.now(timezone.utc),
        in_offer=True,
        manager_id=MANAGER_ID,
    )


class TestManagerOrdersEndpoint:
    """Tests for POST /manager/orders."""

    @pytest.mark.asyncio
    async def test_returns_orders_for_manager(self) -> None:
        order = _make_order()
        manager_service = MagicMock()
        manager_service.list_orders_for_manager = AsyncMock(
            return_value=([order], 1)
        )

        dispatcher = MagicMock()
        dispatcher.__getitem__ = lambda self, k: manager_service

        cfg = MagicMock()
        cfg.bot.bot_username = "testbot"

        request = MagicMock()
        request.app.state.dispatcher = dispatcher
        request.app.state.config = cfg

        body = ManagerOrdersRequest(init_data="x")

        with patch(
            "ugc_bot.miniapp.api._ensure_user_and_get_id",
            new=AsyncMock(return_value=MANAGER_ID),
        ):
            result = await manager_orders(request, body)

        assert result.total == 1
        assert len(result.orders) == 1
        assert result.orders[0].order_id == str(ORDER_ID)
        assert result.orders[0].status == "active"
        assert result.orders[0].price == 1000.0

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_orders(self) -> None:
        manager_service = MagicMock()
        manager_service.list_orders_for_manager = AsyncMock(
            return_value=([], 0)
        )

        dispatcher = MagicMock()
        dispatcher.__getitem__ = lambda self, k: manager_service

        cfg = MagicMock()
        cfg.bot.bot_username = "testbot"

        request = MagicMock()
        request.app.state.dispatcher = dispatcher
        request.app.state.config = cfg

        body = ManagerOrdersRequest(init_data="x")

        with patch(
            "ugc_bot.miniapp.api._ensure_user_and_get_id",
            new=AsyncMock(return_value=MANAGER_ID),
        ):
            result = await manager_orders(request, body)

        assert result.total == 0
        assert result.orders == []

    @pytest.mark.asyncio
    async def test_new_order_gets_payment_link(self) -> None:
        order = _make_order()
        order = Order(
            order_id=order.order_id,
            advertiser_id=order.advertiser_id,
            order_type=order.order_type,
            product_link=order.product_link,
            offer_text=order.offer_text,
            barter_description=None,
            price=order.price,
            bloggers_needed=order.bloggers_needed,
            status=OrderStatus.NEW,
            created_at=order.created_at,
            completed_at=None,
        )
        manager_service = MagicMock()
        manager_service.list_orders_for_manager = AsyncMock(
            return_value=([order], 1)
        )

        dispatcher = MagicMock()
        dispatcher.__getitem__ = lambda self, k: manager_service

        cfg = MagicMock()
        cfg.bot.bot_username = "testbot"

        request = MagicMock()
        request.app.state.dispatcher = dispatcher
        request.app.state.config = cfg

        body = ManagerOrdersRequest(init_data="x")

        with patch(
            "ugc_bot.miniapp.api._ensure_user_and_get_id",
            new=AsyncMock(return_value=MANAGER_ID),
        ):
            result = await manager_orders(request, body)

        assert result.orders[0].payment_link != ""


class TestManagerCreatorsEndpoint:
    """Tests for POST /manager/orders/{order_id}/creators."""

    @pytest.mark.asyncio
    async def test_returns_creators_for_manager(self) -> None:
        dispatch = _make_dispatch()

        manager_service = MagicMock()
        manager_service.is_manager_for_order = AsyncMock(return_value=True)
        manager_service.list_creators_for_order = AsyncMock(
            return_value=([dispatch], 1)
        )

        user = MagicMock()
        user.telegram = "blogger_user"
        user_repo = MagicMock()
        user_repo.get_by_ids = AsyncMock(
            return_value={BLOGGER_ID: user}
        )

        profile = MagicMock()
        profile.instagram_url = "https://instagram.com/blogger"
        profile_service = MagicMock()
        profile_service.get_blogger_profiles = AsyncMock(
            return_value={BLOGGER_ID: profile}
        )

        deps = {
            "manager_service": manager_service,
            "user_repo": user_repo,
            "profile_service": profile_service,
        }

        dispatcher = MagicMock()
        dispatcher.__getitem__ = lambda self, k: deps[k]

        request = MagicMock()
        request.app.state.dispatcher = dispatcher

        body = ManagerCreatorsRequest(init_data="x", in_offer=True)

        with patch(
            "ugc_bot.miniapp.api._ensure_user_and_get_id",
            new=AsyncMock(return_value=MANAGER_ID),
        ):
            result = await manager_creators(request, ORDER_ID, body)

        assert result.total == 1
        assert len(result.creators) == 1
        assert result.creators[0].telegram == "blogger_user"
        assert (
            result.creators[0].instagram_url == "https://instagram.com/blogger"
        )

    @pytest.mark.asyncio
    async def test_403_when_not_manager_for_order(self) -> None:
        manager_service = MagicMock()
        manager_service.is_manager_for_order = AsyncMock(return_value=False)

        deps = {
            "manager_service": manager_service,
            "profile_service": MagicMock(),
        }

        dispatcher = MagicMock()
        dispatcher.__getitem__ = lambda self, k: deps[k]

        request = MagicMock()
        request.app.state.dispatcher = dispatcher

        body = ManagerCreatorsRequest(init_data="x", in_offer=True)

        with (
            patch(
                "ugc_bot.miniapp.api._ensure_user_and_get_id",
                new=AsyncMock(return_value=MANAGER_ID),
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await manager_creators(request, ORDER_ID, body)

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_creators_with_no_profile(self) -> None:
        """Creator with no profile returns None fields."""
        dispatch = _make_dispatch()

        manager_service = MagicMock()
        manager_service.is_manager_for_order = AsyncMock(return_value=True)
        manager_service.list_creators_for_order = AsyncMock(
            return_value=([dispatch], 1)
        )

        user_repo = MagicMock()
        user_repo.get_by_ids = AsyncMock(return_value={})

        profile_service = MagicMock()
        profile_service.get_blogger_profiles = AsyncMock(return_value={})

        deps = {
            "manager_service": manager_service,
            "user_repo": user_repo,
            "profile_service": profile_service,
        }

        dispatcher = MagicMock()
        dispatcher.__getitem__ = lambda self, k: deps[k]

        request = MagicMock()
        request.app.state.dispatcher = dispatcher

        body = ManagerCreatorsRequest(init_data="x", in_offer=False)

        with patch(
            "ugc_bot.miniapp.api._ensure_user_and_get_id",
            new=AsyncMock(return_value=MANAGER_ID),
        ):
            result = await manager_creators(request, ORDER_ID, body)

        assert result.total == 1
        assert result.creators[0].telegram is None
        assert result.creators[0].instagram_url is None


class TestMeEndpointIsManager:
    """Tests for is_manager field in me endpoint."""

    @pytest.mark.asyncio
    async def test_me_is_manager_true(self) -> None:
        from ugc_bot.miniapp.api import InitDataBody, me

        user = MagicMock()
        user.external_id = "123"
        user.country = None
        user.language = None

        profile_service = MagicMock()
        profile_service.get_advertiser_profile = AsyncMock(return_value=None)
        profile_service.get_blogger_profile = AsyncMock(return_value=None)
        profile_service.get_user_by_external = AsyncMock(return_value=user)

        manager_service = MagicMock()
        manager_service.is_manager = AsyncMock(return_value=True)

        def dispatcher_get(key):
            if key == "country_repo":
                return None
            if key == "manager_service":
                return manager_service
            return None

        dispatcher = MagicMock()
        dispatcher.__getitem__ = lambda self, k: profile_service
        dispatcher.get = dispatcher_get

        uid = uuid4()
        request = MagicMock()
        request.app.state.dispatcher = dispatcher
        request.app.state.config.market.default_locale = "ru"

        body = InitDataBody(init_data="x")

        with (
            patch(
                "ugc_bot.miniapp.api._ensure_user_and_get_id",
                new=AsyncMock(return_value=uid),
            ),
            patch(
                "ugc_bot.miniapp.api._get_telegram_user_id",
                return_value="123",
            ),
        ):
            result = await me(request, body)

        assert result.is_manager is True
