"""Tests for miniapp manager endpoints."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from ugc_bot.domain.entities import OfferDispatch, Order
from ugc_bot.domain.enums import OrderStatus, OrderType
from ugc_bot.miniapp.api import (
    CreatorDetailRequest,
    ManagerCreatorsRequest,
    ManagerOrdersRequest,
    UgcVideoRequest,
    manager_creator_detail,
    manager_creators,
    manager_orders,
    manager_set_ugc_video,
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
        user_repo.get_by_ids = AsyncMock(return_value={BLOGGER_ID: user})

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


class TestManagerCreatorDetailEndpoint:
    """Tests for POST /manager/orders/{order_id}/creators/{blogger_id}."""

    def _make_deps(
        self,
        is_manager: bool = True,
        dispatch: OfferDispatch | None = None,
        user: MagicMock | None = None,
        profile: MagicMock | None = None,
    ) -> tuple[MagicMock, MagicMock]:
        manager_service = MagicMock()
        manager_service.is_manager_for_order = AsyncMock(
            return_value=is_manager
        )

        dispatch_repo = MagicMock()
        dispatch_repo.get_by_order_and_blogger = AsyncMock(
            return_value=dispatch
        )

        user_repo = MagicMock()
        user_repo.get_by_id = AsyncMock(return_value=user)

        profile_service = MagicMock()
        profile_service.get_blogger_profile = AsyncMock(return_value=profile)

        deps = {
            "manager_service": manager_service,
            "offer_dispatch_repo": dispatch_repo,
            "user_repo": user_repo,
            "profile_service": profile_service,
        }

        dispatcher = MagicMock()
        dispatcher.__getitem__ = lambda self, k: deps[k]

        request = MagicMock()
        request.app.state.dispatcher = dispatcher
        return request, dispatcher

    @pytest.mark.asyncio
    async def test_returns_creator_detail(self) -> None:
        dispatch = _make_dispatch()
        dispatch = OfferDispatch(
            order_id=dispatch.order_id,
            blogger_id=dispatch.blogger_id,
            created_at=dispatch.created_at,
            in_offer=dispatch.in_offer,
            manager_id=dispatch.manager_id,
            ugc_video_url="https://example.com/video",
        )

        user = MagicMock()
        user.telegram = "creator_tg"

        profile = MagicMock()
        profile.instagram_url = "https://instagram.com/creator"

        request, _ = self._make_deps(
            dispatch=dispatch, user=user, profile=profile
        )
        body = CreatorDetailRequest(init_data="x")

        with patch(
            "ugc_bot.miniapp.api._ensure_user_and_get_id",
            new=AsyncMock(return_value=MANAGER_ID),
        ):
            result = await manager_creator_detail(
                request, ORDER_ID, BLOGGER_ID, body
            )

        assert result.blogger_id == str(BLOGGER_ID)
        assert result.telegram == "creator_tg"
        assert result.instagram_url == "https://instagram.com/creator"
        assert result.ugc_video_url == "https://example.com/video"

    @pytest.mark.asyncio
    async def test_403_when_not_manager(self) -> None:
        request, _ = self._make_deps(is_manager=False)
        body = CreatorDetailRequest(init_data="x")

        with (
            patch(
                "ugc_bot.miniapp.api._ensure_user_and_get_id",
                new=AsyncMock(return_value=MANAGER_ID),
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await manager_creator_detail(request, ORDER_ID, BLOGGER_ID, body)

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_404_when_dispatch_missing(self) -> None:
        request, _ = self._make_deps(dispatch=None)
        body = CreatorDetailRequest(init_data="x")

        with (
            patch(
                "ugc_bot.miniapp.api._ensure_user_and_get_id",
                new=AsyncMock(return_value=MANAGER_ID),
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await manager_creator_detail(request, ORDER_ID, BLOGGER_ID, body)

        assert exc_info.value.status_code == 404


class TestManagerSetUgcVideoEndpoint:
    """Tests for POST /manager/orders/{order_id}/creators/{blogger_id}/ugc-video."""  # noqa: E501

    def _make_request(
        self,
        is_manager: bool = True,
        order: Order | None = None,
        dispatch: OfferDispatch | None = None,
        previous_url: str | None = None,
    ) -> MagicMock:
        manager_service = MagicMock()
        manager_service.is_manager_for_order = AsyncMock(
            return_value=is_manager
        )

        if order is None:
            order = Order(
                order_id=ORDER_ID,
                advertiser_id=uuid4(),
                order_type=OrderType.UGC_ONLY,
                product_link="https://example.com",
                offer_text="Offer",
                barter_description=None,
                price=500.0,
                bloggers_needed=2,
                status=OrderStatus.ACTIVE,
                created_at=datetime.now(timezone.utc),
                completed_at=None,
            )

        order_repo = MagicMock()
        order_repo.get_by_id = AsyncMock(return_value=order)

        if dispatch is None:
            dispatch = OfferDispatch(
                order_id=ORDER_ID,
                blogger_id=BLOGGER_ID,
                created_at=datetime.now(timezone.utc),
                in_offer=True,
                manager_id=MANAGER_ID,
                ugc_video_url=previous_url,
            )

        dispatch_repo = MagicMock()
        dispatch_repo.get_by_order_and_blogger = AsyncMock(
            return_value=dispatch
        )
        dispatch_repo.set_ugc_video_url = AsyncMock()

        user_repo = MagicMock()
        user_repo.get_by_id = AsyncMock(return_value=None)

        messenger_client = MagicMock()
        messenger_client.send_text = AsyncMock()

        bot_texts_service = MagicMock()
        bot_texts_service.get = MagicMock(return_value="msg")

        deps = {
            "manager_service": manager_service,
            "order_repo": order_repo,
            "offer_dispatch_repo": dispatch_repo,
            "user_repo": user_repo,
            "messenger_client": messenger_client,
            "bot_texts_service": bot_texts_service,
        }

        dispatcher = MagicMock()
        dispatcher.__getitem__ = lambda self, k: deps[k]

        request = MagicMock()
        request.app.state.dispatcher = dispatcher
        return request

    @pytest.mark.asyncio
    async def test_returns_ok_true(self) -> None:
        request = self._make_request()
        body = UgcVideoRequest(init_data="x", url="https://example.com/video")

        with patch(
            "ugc_bot.miniapp.api._ensure_user_and_get_id",
            new=AsyncMock(return_value=MANAGER_ID),
        ):
            result = await manager_set_ugc_video(
                request, ORDER_ID, BLOGGER_ID, body
            )

        assert result == {"ok": True}

    @pytest.mark.asyncio
    async def test_403_when_not_manager(self) -> None:
        request = self._make_request(is_manager=False)
        body = UgcVideoRequest(init_data="x", url="https://example.com/video")

        with (
            patch(
                "ugc_bot.miniapp.api._ensure_user_and_get_id",
                new=AsyncMock(return_value=MANAGER_ID),
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await manager_set_ugc_video(request, ORDER_ID, BLOGGER_ID, body)

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_404_when_order_missing(self) -> None:
        manager_service = MagicMock()
        manager_service.is_manager_for_order = AsyncMock(return_value=True)

        order_repo = MagicMock()
        order_repo.get_by_id = AsyncMock(return_value=None)

        deps = {
            "manager_service": manager_service,
            "order_repo": order_repo,
        }
        dispatcher = MagicMock()
        dispatcher.__getitem__ = lambda self, k: deps[k]

        request = MagicMock()
        request.app.state.dispatcher = dispatcher

        body = UgcVideoRequest(init_data="x", url="https://example.com/video")

        with (
            patch(
                "ugc_bot.miniapp.api._ensure_user_and_get_id",
                new=AsyncMock(return_value=MANAGER_ID),
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await manager_set_ugc_video(request, ORDER_ID, BLOGGER_ID, body)

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_404_when_dispatch_missing(self) -> None:
        order = Order(
            order_id=ORDER_ID,
            advertiser_id=uuid4(),
            order_type=OrderType.UGC_ONLY,
            product_link="https://example.com",
            offer_text="Offer",
            barter_description=None,
            price=500.0,
            bloggers_needed=2,
            status=OrderStatus.ACTIVE,
            created_at=datetime.now(timezone.utc),
            completed_at=None,
        )

        manager_service = MagicMock()
        manager_service.is_manager_for_order = AsyncMock(return_value=True)

        order_repo = MagicMock()
        order_repo.get_by_id = AsyncMock(return_value=order)

        dispatch_repo = MagicMock()
        dispatch_repo.get_by_order_and_blogger = AsyncMock(return_value=None)

        deps = {
            "manager_service": manager_service,
            "order_repo": order_repo,
            "offer_dispatch_repo": dispatch_repo,
        }
        dispatcher = MagicMock()
        dispatcher.__getitem__ = lambda self, k: deps[k]

        request = MagicMock()
        request.app.state.dispatcher = dispatcher

        body = UgcVideoRequest(init_data="x", url="https://example.com/video")

        with (
            patch(
                "ugc_bot.miniapp.api._ensure_user_and_get_id",
                new=AsyncMock(return_value=MANAGER_ID),
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await manager_set_ugc_video(request, ORDER_ID, BLOGGER_ID, body)

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_no_notification_on_update(self) -> None:
        """When previous_url is already set, no notification is sent."""
        request = self._make_request(previous_url="https://old.com/video")
        dispatcher = request.app.state.dispatcher

        body = UgcVideoRequest(init_data="x", url="https://new.com/video")

        with patch(
            "ugc_bot.miniapp.api._ensure_user_and_get_id",
            new=AsyncMock(return_value=MANAGER_ID),
        ):
            result = await manager_set_ugc_video(
                request, ORDER_ID, BLOGGER_ID, body
            )

        assert result == {"ok": True}
        # messenger_client.send_text should NOT have been called
        messenger_client = dispatcher["messenger_client"]
        messenger_client.send_text.assert_not_called()
