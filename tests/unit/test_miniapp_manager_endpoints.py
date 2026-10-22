"""Tests for miniapp manager endpoints."""

from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from ugc_bot.domain.entities import AdvertiserProfile, OfferDispatch, Order
from ugc_bot.domain.enums import OrderStatus, OrderType, RejectionReason
from ugc_bot.miniapp.api import (
    CreatorDetailRequest,
    InitDataBody,
    ManagerCreatorsRequest,
    ManagerFeedbackRequest,
    ManagerOrdersRequest,
    UgcVideoRequest,
    manager_add_creator,
    manager_creator_detail,
    manager_creators,
    manager_feedback,
    manager_orders,
    manager_remove_creator,
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


@pytest.mark.asyncio
async def test_other_manager_cannot_read_creator() -> None:
    from dataclasses import replace

    dispatch = replace(_make_dispatch(), manager_id=uuid4())
    request, dispatcher = TestManagerCreatorDetailEndpoint()._make_deps(
        dispatch=dispatch
    )
    with (
        patch(
            "ugc_bot.miniapp.api._ensure_user_and_get_id",
            new=AsyncMock(return_value=MANAGER_ID),
        ),
        pytest.raises(HTTPException) as exc,
    ):
        await manager_creator_detail(
            request, ORDER_ID, BLOGGER_ID, CreatorDetailRequest(init_data="x")
        )
    assert exc.value.status_code == 403
    dispatcher["user_repo"].get_by_id.assert_not_awaited()
    dispatcher["profile_service"].get_blogger_profile.assert_not_awaited()
    assert "phone" not in exc.value.detail


def _pair_request(dispatch: OfferDispatch | None) -> tuple[MagicMock, dict]:
    interaction = MagicMock(interaction_id=uuid4())
    deps = {
        "manager_service": MagicMock(
            is_manager_for_order=AsyncMock(return_value=True)
        ),
        "order_repo": MagicMock(
            get_by_id=AsyncMock(return_value=_make_order())
        ),
        "offer_dispatch_repo": MagicMock(
            get_by_order_and_blogger=AsyncMock(return_value=dispatch),
            set_ugc_video_url=AsyncMock(),
            set_in_offer=AsyncMock(),
            set_manager=AsyncMock(),
            count_accepted_by_order=AsyncMock(return_value=0),
        ),
        "interaction_service": MagicMock(
            after_feedback_commit=AsyncMock(),
            get_or_create=AsyncMock(return_value=interaction),
            reactivate_or_create_for_contacts_sent=AsyncMock(),
            record_advertiser_feedback=AsyncMock(return_value=interaction),
        ),
        "user_repo": MagicMock(get_by_id=AsyncMock(return_value=None)),
        "messenger_client": MagicMock(send_text=AsyncMock()),
        "bot_texts_service": MagicMock(
            get=AsyncMock(return_value="{manager_telegram}")
        ),
    }
    request = MagicMock()
    request.app.state.dispatcher = deps
    return request, deps


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["video", "remove", "feedback", "add"])
@pytest.mark.parametrize(
    "assignment",
    [
        "foreign",
        "missing",
        "unassigned",
        "other_order",
        "other_creator",
        "invalid_identity",
    ],
)
async def test_other_manager_cannot_mutate_creator(
    operation: str, assignment: str
) -> None:
    dispatch = replace(
        _make_dispatch(), manager_id=uuid4(), in_offer=operation != "add"
    )
    actor_id = MANAGER_ID
    if assignment == "missing":
        dispatch = None
    elif assignment == "unassigned":
        dispatch = replace(dispatch, manager_id=None)
    elif assignment == "other_order":
        dispatch = replace(dispatch, order_id=uuid4())
    elif assignment == "other_creator":
        dispatch = replace(dispatch, blogger_id=uuid4())
    elif assignment == "invalid_identity":
        actor_id = None
    request, deps = _pair_request(dispatch)
    endpoint, body = {
        "video": (
            manager_set_ugc_video,
            UgcVideoRequest(init_data="x", url="https://example.com/v"),
        ),
        "remove": (manager_remove_creator, InitDataBody(init_data="x")),
        "feedback": (
            manager_feedback,
            ManagerFeedbackRequest(init_data="x", status="ok"),
        ),
        "add": (manager_add_creator, InitDataBody(init_data="x")),
    }[operation]
    with (
        patch(
            "ugc_bot.miniapp.api._ensure_user_and_get_id",
            new=AsyncMock(return_value=actor_id),
        ),
        patch("ugc_bot.miniapp.api.send_with_retry", new=AsyncMock()) as send,
        pytest.raises(HTTPException) as exc,
    ):
        await endpoint(request, ORDER_ID, BLOGGER_ID, body)
    assert exc.value.status_code == (404 if assignment == "missing" else 403)
    for name in ["set_ugc_video_url", "set_in_offer", "set_manager"]:
        getattr(deps["offer_dispatch_repo"], name).assert_not_awaited()
    deps["interaction_service"].get_or_create.assert_not_awaited()
    deps[
        "interaction_service"
    ].reactivate_or_create_for_contacts_sent.assert_not_awaited()
    deps["interaction_service"].record_advertiser_feedback.assert_not_awaited()
    assert all(
        call.args[0] != BLOGGER_ID
        for call in deps["user_repo"].get_by_id.await_args_list
    )
    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_reserve_return_uses_current_manager() -> None:
    from contextlib import asynccontextmanager

    from ugc_bot.application.services.manager_service import ManagerService

    session = object()
    events = []

    @asynccontextmanager
    async def transaction():
        yield session
        events.append("commit")

    old_manager = uuid4()
    dispatch = replace(_make_dispatch(), in_offer=False, manager_id=old_manager)
    request, deps = _pair_request(dispatch)
    creator = MagicMock(telegram_id=123, language="ru")
    current = MagicMock(telegram="current_manager")
    stale = MagicMock(telegram="stale_manager")
    deps["user_repo"].get_by_id.side_effect = lambda uid, **kw: {
        BLOGGER_ID: creator,
        MANAGER_ID: current,
        old_manager: stale,
    }.get(uid)
    deps["manager_service"] = ManagerService(
        manager_order_repo=MagicMock(),
        user_repo=deps["user_repo"],
        order_repo=deps["order_repo"],
        offer_dispatch_repo=deps["offer_dispatch_repo"],
        transaction_manager=MagicMock(transaction=transaction),
    )

    async def send_after_commit(*args, **kwargs):
        assert events == ["commit"]

    with (
        patch(
            "ugc_bot.miniapp.api._ensure_user_and_get_id",
            new=AsyncMock(return_value=MANAGER_ID),
        ),
        patch(
            "ugc_bot.miniapp.api._is_user_admin",
            new=AsyncMock(return_value=True),
        ),
        patch(
            "ugc_bot.miniapp.api.send_with_retry",
            new=AsyncMock(side_effect=send_after_commit),
        ) as send,
    ):
        result = await manager_add_creator(
            request, ORDER_ID, BLOGGER_ID, InitDataBody(init_data="x")
        )
        deps[
            "offer_dispatch_repo"
        ].get_by_order_and_blogger.return_value = replace(
            dispatch, in_offer=True, manager_id=MANAGER_ID
        )
        with pytest.raises(HTTPException) as repeated:
            await manager_add_creator(
                request, ORDER_ID, BLOGGER_ID, InitDataBody(init_data="x")
            )
        assert repeated.value.status_code == 409
    send.assert_awaited_once()
    for method in ["set_in_offer", "set_manager"]:
        write = getattr(deps["offer_dispatch_repo"], method)
        write.assert_awaited_once()
        assert write.await_args.kwargs["session"] is session
    assert result == {"ok": True}
    assert send.await_args.kwargs["text"] == "@current_manager"
    assert all(
        call.args[0] != old_manager
        for call in deps["user_repo"].get_by_id.await_args_list
    )
    assert deps["offer_dispatch_repo"].set_manager.await_args.args == (
        ORDER_ID,
        BLOGGER_ID,
        MANAGER_ID,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["detail", "video", "feedback"])
async def test_reserve_assignment_cannot_disclose_contacts_or_mutate(
    operation: str,
) -> None:
    request, deps = _pair_request(replace(_make_dispatch(), in_offer=False))
    deps["profile_service"] = MagicMock(
        get_blogger_profile=AsyncMock(return_value=None)
    )
    endpoint, body = {
        "detail": (manager_creator_detail, CreatorDetailRequest(init_data="x")),
        "video": (
            manager_set_ugc_video,
            UgcVideoRequest(init_data="x", url="https://example.com/v"),
        ),
        "feedback": (
            manager_feedback,
            ManagerFeedbackRequest(init_data="x", status="ok"),
        ),
    }[operation]
    with (
        patch(
            "ugc_bot.miniapp.api._ensure_user_and_get_id",
            new=AsyncMock(return_value=MANAGER_ID),
        ),
        pytest.raises(HTTPException) as exc,
    ):
        await endpoint(request, ORDER_ID, BLOGGER_ID, body)
    assert exc.value.status_code == 403
    deps["interaction_service"].get_or_create.assert_not_awaited()
    deps["offer_dispatch_repo"].set_ugc_video_url.assert_not_awaited()
    deps["profile_service"].get_blogger_profile.assert_not_awaited()


@pytest.mark.asyncio
async def test_stale_reserve_assignment_denied_before_write() -> None:
    from ugc_bot.application.services.manager_service import ManagerService

    own = replace(_make_dispatch(), in_offer=False)
    stale = replace(own, manager_id=uuid4())
    request, deps = _pair_request(own)
    deps["offer_dispatch_repo"].get_by_order_and_blogger.side_effect = [
        own,
        stale,
    ]
    deps["manager_service"] = ManagerService(
        manager_order_repo=MagicMock(
            list_by_order=AsyncMock(
                return_value=[MagicMock(user_id=MANAGER_ID)]
            )
        ),
        user_repo=deps["user_repo"],
        order_repo=deps["order_repo"],
        offer_dispatch_repo=deps["offer_dispatch_repo"],
    )
    with (
        patch(
            "ugc_bot.miniapp.api._ensure_user_and_get_id",
            new=AsyncMock(return_value=MANAGER_ID),
        ),
        patch("ugc_bot.miniapp.api.send_with_retry", new=AsyncMock()) as send,
        pytest.raises(HTTPException) as exc,
    ):
        await manager_add_creator(
            request, ORDER_ID, BLOGGER_ID, InitDataBody(init_data="x")
        )
    assert exc.value.status_code == 403
    deps["offer_dispatch_repo"].set_manager.assert_not_awaited()
    deps["offer_dispatch_repo"].set_in_offer.assert_not_awaited()
    deps[
        "interaction_service"
    ].reactivate_or_create_for_contacts_sent.assert_not_awaited()
    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_role_admin_can_read_foreign_pair_with_audit(caplog) -> None:
    request, deps = _pair_request(replace(_make_dispatch(), manager_id=uuid4()))
    deps["profile_service"] = MagicMock(
        get_blogger_profile=AsyncMock(return_value=None)
    )
    admin = MagicMock(admin=True, telegram="admin_contact")
    creator = MagicMock(telegram="creator_contact")
    deps["user_repo"].get_by_id.side_effect = lambda uid: (
        admin if uid == MANAGER_ID else creator
    )
    deps["manager_service"].is_manager_for_order.return_value = False
    with (
        patch(
            "ugc_bot.miniapp.api._ensure_user_and_get_id",
            new=AsyncMock(return_value=MANAGER_ID),
        ),
        caplog.at_level("INFO"),
    ):
        result = await manager_creator_detail(
            request, ORDER_ID, BLOGGER_ID, CreatorDetailRequest(init_data="x")
        )
    assert result.telegram == "creator_contact"
    deps["manager_service"].is_manager_for_order.assert_not_awaited()
    assert any(
        getattr(record, "event", None) == "admin_manager_pair_access"
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_own_creator_remove_keeps_legacy_response() -> None:
    request, deps = _pair_request(_make_dispatch())
    with patch(
        "ugc_bot.miniapp.api._ensure_user_and_get_id",
        new=AsyncMock(return_value=MANAGER_ID),
    ):
        result = await manager_remove_creator(
            request, ORDER_ID, BLOGGER_ID, InitDataBody(init_data="x")
        )
    assert result["ok"] is True
    deps["offer_dispatch_repo"].set_in_offer.assert_awaited_once_with(
        ORDER_ID,
        BLOGGER_ID,
        False,
        session=deps["offer_dispatch_repo"].set_in_offer.await_args.kwargs[
            "session"
        ],
    )
    deps["interaction_service"].record_advertiser_feedback.assert_awaited_once()


@pytest.mark.asyncio
async def test_reserve_return_rechecks_already_active_before_writes() -> None:
    from ugc_bot.application.services.manager_service import ManagerService

    reserve = replace(_make_dispatch(), in_offer=False)
    request, deps = _pair_request(reserve)
    deps["offer_dispatch_repo"].get_by_order_and_blogger.side_effect = [
        reserve,
        _make_dispatch(),
    ]
    deps["manager_service"] = ManagerService(
        manager_order_repo=MagicMock(),
        user_repo=deps["user_repo"],
        order_repo=deps["order_repo"],
        offer_dispatch_repo=deps["offer_dispatch_repo"],
    )
    with (
        patch(
            "ugc_bot.miniapp.api._ensure_user_and_get_id",
            new=AsyncMock(return_value=MANAGER_ID),
        ),
        patch(
            "ugc_bot.miniapp.api._is_user_admin",
            new=AsyncMock(return_value=True),
        ),
        patch("ugc_bot.miniapp.api.send_with_retry", new=AsyncMock()) as send,
        pytest.raises(HTTPException) as exc,
    ):
        await manager_add_creator(
            request, ORDER_ID, BLOGGER_ID, InitDataBody(init_data="x")
        )
    assert exc.value.status_code == 409
    deps["offer_dispatch_repo"].set_manager.assert_not_awaited()
    deps["offer_dispatch_repo"].set_in_offer.assert_not_awaited()
    deps[
        "interaction_service"
    ].reactivate_or_create_for_contacts_sent.assert_not_awaited()
    send.assert_not_awaited()


class TestManagerOrdersEndpoint:
    """Tests for POST /manager/orders."""

    @pytest.mark.asyncio
    async def test_returns_orders_for_manager(self) -> None:
        order = _make_order()
        manager_service = MagicMock()
        manager_service.list_orders_for_manager = AsyncMock(
            return_value=([order], 1)
        )
        profile_service = MagicMock()
        profile_service.get_advertiser_profiles = AsyncMock(
            return_value={
                order.advertiser_id: AdvertiserProfile(
                    user_id=order.advertiser_id,
                    phone="+70000000000",
                    brand="TestBrand",
                )
            }
        )

        services = {
            "manager_service": manager_service,
            "profile_service": profile_service,
        }
        dispatcher = MagicMock()
        dispatcher.__getitem__ = lambda self, k: services[k]
        dispatcher.get = lambda k: services.get(k)

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
        assert result.orders[0].brand_name == "TestBrand"

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_orders(self) -> None:
        manager_service = MagicMock()
        manager_service.list_orders_for_manager = AsyncMock(
            return_value=([], 0)
        )
        profile_service = MagicMock()
        profile_service.get_advertiser_profiles = AsyncMock(return_value={})

        services = {
            "manager_service": manager_service,
            "profile_service": profile_service,
        }
        dispatcher = MagicMock()
        dispatcher.__getitem__ = lambda self, k: services[k]
        dispatcher.get = lambda k: services.get(k)

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
        profile_service = MagicMock()
        profile_service.get_advertiser_profiles = AsyncMock(return_value={})

        services = {
            "manager_service": manager_service,
            "profile_service": profile_service,
        }
        dispatcher = MagicMock()
        dispatcher.__getitem__ = lambda self, k: services[k]
        dispatcher.get = lambda k: services.get(k)

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
        user.username = "Blogger Name"
        user_repo = MagicMock()
        user_repo.get_by_ids = AsyncMock(return_value={BLOGGER_ID: user})

        profile = MagicMock()
        profile.instagram_url = "https://instagram.com/blogger"
        profile.phone = "+79001234567"
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
        assert result.creators[0].name == "Blogger Name"
        assert result.creators[0].desired_price is None
        assert result.creators[0].phone == "+79001234567"

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
        user.telegram_id = "123"
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
                "ugc_bot.miniapp.api._get_external_id",
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
        profile.phone = "+79009876543"

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
        assert result.phone == "+79009876543"

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

        interaction = MagicMock()
        interaction.interaction_id = uuid4()
        interaction_service = MagicMock(after_feedback_commit=AsyncMock())
        interaction_service.get_or_create = AsyncMock(return_value=interaction)

        deps = {
            "manager_service": manager_service,
            "order_repo": order_repo,
            "offer_dispatch_repo": dispatch_repo,
            "user_repo": user_repo,
            "messenger_client": messenger_client,
            "bot_texts_service": bot_texts_service,
            "interaction_service": interaction_service,
        }

        dispatcher = MagicMock()
        dispatcher.__getitem__ = lambda self, k: deps[k]

        request = MagicMock()
        request.app.state.dispatcher = dispatcher
        return request

    @pytest.mark.asyncio
    async def test_returns_ok_and_interaction_id(self) -> None:
        request = self._make_request()
        body = UgcVideoRequest(init_data="x", url="https://example.com/video")

        with patch(
            "ugc_bot.miniapp.api._ensure_user_and_get_id",
            new=AsyncMock(return_value=MANAGER_ID),
        ):
            result = await manager_set_ugc_video(
                request, ORDER_ID, BLOGGER_ID, body
            )

        assert result["ok"] is True
        assert "interaction_id" in result

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

        assert result["ok"] is True
        assert "interaction_id" in result
        # messenger_client.send_text should NOT have been called
        messenger_client = dispatcher["messenger_client"]
        messenger_client.send_text.assert_not_called()


INTERACTION_ID = UUID("00000000-0000-0000-0000-000000000c01")


class TestManagerFeedbackEndpoint:
    """Tests for manager feedback endpoint."""

    @pytest.mark.asyncio
    async def test_feedback_ok_records_advertiser_feedback(self) -> None:
        order = _make_order()

        manager_service = MagicMock()
        manager_service.is_manager_for_order = AsyncMock(return_value=True)

        order_repo = MagicMock()
        order_repo.get_by_id = AsyncMock(return_value=order)

        interaction = MagicMock()
        interaction.interaction_id = INTERACTION_ID

        interaction_service = MagicMock(after_feedback_commit=AsyncMock())
        interaction_service.get_or_create = AsyncMock(return_value=interaction)

        updated_interaction = MagicMock()
        updated_interaction.interaction_id = INTERACTION_ID
        interaction_service.record_advertiser_feedback = AsyncMock(
            return_value=updated_interaction
        )

        deps = {
            "manager_service": manager_service,
            "order_repo": order_repo,
            "offer_dispatch_repo": MagicMock(
                get_by_order_and_blogger=AsyncMock(
                    return_value=_make_dispatch()
                )
            ),
            "interaction_service": interaction_service,
        }

        dispatcher = MagicMock()
        dispatcher.__getitem__ = lambda self, k: deps[k]

        request = MagicMock()
        request.app.state.dispatcher = dispatcher

        body = ManagerFeedbackRequest(
            init_data="x",
            status="ok",
        )

        with patch(
            "ugc_bot.miniapp.api._ensure_user_and_get_id",
            new=AsyncMock(return_value=MANAGER_ID),
        ):
            result = await manager_feedback(request, ORDER_ID, BLOGGER_ID, body)

        assert result == {"ok": True, "interaction_id": str(INTERACTION_ID)}
        interaction_service.get_or_create.assert_awaited_once_with(
            ORDER_ID,
            BLOGGER_ID,
            order.advertiser_id,
            session=interaction_service.get_or_create.await_args.kwargs[
                "session"
            ],
        )
        interaction_service.record_advertiser_feedback.assert_awaited_once_with(
            INTERACTION_ID,
            "✅ Всё прошло хорошо",
            session=interaction_service.get_or_create.await_args.kwargs[
                "session"
            ],
        )

    @pytest.mark.asyncio
    async def test_feedback_no_deal_records_advertiser_feedback(self) -> None:
        order = _make_order()
        interaction = MagicMock()
        interaction.interaction_id = INTERACTION_ID

        updated = MagicMock()
        updated.interaction_id = INTERACTION_ID

        interaction_service = MagicMock(after_feedback_commit=AsyncMock())
        interaction_service.get_or_create = AsyncMock(return_value=interaction)
        interaction_service.record_advertiser_feedback = AsyncMock(
            return_value=updated
        )

        deps = {
            "manager_service": MagicMock(
                is_manager_for_order=AsyncMock(return_value=True)
            ),
            "order_repo": MagicMock(get_by_id=AsyncMock(return_value=order)),
            "offer_dispatch_repo": MagicMock(
                get_by_order_and_blogger=AsyncMock(
                    return_value=_make_dispatch()
                )
            ),
            "interaction_service": interaction_service,
        }

        dispatcher = MagicMock()
        dispatcher.__getitem__ = lambda self, k: deps[k]

        request = MagicMock()
        request.app.state.dispatcher = dispatcher

        body = ManagerFeedbackRequest(init_data="x", status="no_deal")

        with patch(
            "ugc_bot.miniapp.api._ensure_user_and_get_id",
            new=AsyncMock(return_value=MANAGER_ID),
        ):
            result = await manager_feedback(request, ORDER_ID, BLOGGER_ID, body)

        assert result["ok"] is True
        call_args = interaction_service.record_advertiser_feedback.call_args
        assert "❌" in call_args.args[1]

    @pytest.mark.asyncio
    async def test_feedback_issue_creates_complaint(self) -> None:
        order = _make_order()
        interaction = MagicMock()
        interaction.interaction_id = INTERACTION_ID

        updated = MagicMock()
        updated.interaction_id = INTERACTION_ID

        interaction_service = MagicMock(after_feedback_commit=AsyncMock())
        interaction_service.get_or_create = AsyncMock(return_value=interaction)
        interaction_service.record_advertiser_feedback = AsyncMock(
            return_value=updated
        )

        complaint = MagicMock()
        complaint_service = MagicMock()
        complaint_service.get_or_create_for_interaction = AsyncMock(
            return_value=(complaint, True)
        )

        deps = {
            "manager_service": MagicMock(
                is_manager_for_order=AsyncMock(return_value=True)
            ),
            "order_repo": MagicMock(get_by_id=AsyncMock(return_value=order)),
            "offer_dispatch_repo": MagicMock(
                get_by_order_and_blogger=AsyncMock(
                    return_value=_make_dispatch()
                )
            ),
            "interaction_service": interaction_service,
            "complaint_service": complaint_service,
            "user_role_service": MagicMock(),
            "messenger_client": MagicMock(),
        }

        dispatcher = MagicMock()
        dispatcher.__getitem__ = lambda self, k: deps[k]

        request = MagicMock()
        request.app.state.dispatcher = dispatcher

        body = ManagerFeedbackRequest(
            init_data="x", status="issue", issue_description="Обман"
        )

        with (
            patch(
                "ugc_bot.miniapp.api._ensure_user_and_get_id",
                new=AsyncMock(return_value=MANAGER_ID),
            ),
            patch(
                "ugc_bot.miniapp.api.notify_admins_about_complaint",
                new=AsyncMock(),
            ),
        ):
            result = await manager_feedback(request, ORDER_ID, BLOGGER_ID, body)

        assert result["ok"] is True
        complaint_service.get_or_create_for_interaction.assert_awaited_once()
        call_kwargs = (
            complaint_service.get_or_create_for_interaction.call_args.kwargs
        )
        assert call_kwargs["reporter_id"] == MANAGER_ID
        assert call_kwargs["reported_id"] == BLOGGER_ID
        assert "Обман" in call_kwargs["reason"]

    @pytest.mark.asyncio
    async def test_feedback_issue_without_description_returns_422(self) -> None:
        order = _make_order()
        interaction = MagicMock()
        interaction.interaction_id = INTERACTION_ID

        deps = {
            "manager_service": MagicMock(
                is_manager_for_order=AsyncMock(return_value=True)
            ),
            "order_repo": MagicMock(get_by_id=AsyncMock(return_value=order)),
            "offer_dispatch_repo": MagicMock(
                get_by_order_and_blogger=AsyncMock(
                    return_value=_make_dispatch()
                )
            ),
            "interaction_service": MagicMock(
                get_or_create=AsyncMock(return_value=interaction)
            ),
        }

        dispatcher = MagicMock()
        dispatcher.__getitem__ = lambda self, k: deps[k]

        request = MagicMock()
        request.app.state.dispatcher = dispatcher

        body = ManagerFeedbackRequest(init_data="x", status="issue")

        with (
            patch(
                "ugc_bot.miniapp.api._ensure_user_and_get_id",
                new=AsyncMock(return_value=MANAGER_ID),
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await manager_feedback(request, ORDER_ID, BLOGGER_ID, body)

        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_feedback_403_when_not_manager(self) -> None:
        deps = {
            "manager_service": MagicMock(
                is_manager_for_order=AsyncMock(return_value=False)
            ),
        }

        dispatcher = MagicMock()
        dispatcher.__getitem__ = lambda self, k: deps[k]

        request = MagicMock()
        request.app.state.dispatcher = dispatcher

        body = ManagerFeedbackRequest(init_data="x", status="ok")

        with (
            patch(
                "ugc_bot.miniapp.api._ensure_user_and_get_id",
                new=AsyncMock(return_value=MANAGER_ID),
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await manager_feedback(request, ORDER_ID, BLOGGER_ID, body)

        assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_feedback_404_when_order_not_found(self) -> None:
        deps = {
            "manager_service": MagicMock(
                is_manager_for_order=AsyncMock(return_value=True)
            ),
            "order_repo": MagicMock(get_by_id=AsyncMock(return_value=None)),
        }

        dispatcher = MagicMock()
        dispatcher.__getitem__ = lambda self, k: deps[k]

        request = MagicMock()
        request.app.state.dispatcher = dispatcher

        body = ManagerFeedbackRequest(init_data="x", status="ok")

        with (
            patch(
                "ugc_bot.miniapp.api._ensure_user_and_get_id",
                new=AsyncMock(return_value=MANAGER_ID),
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await manager_feedback(request, ORDER_ID, BLOGGER_ID, body)

        assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_feedback_issue_whitespace_description_returns_422(
        self,
    ) -> None:
        order = _make_order()
        interaction = MagicMock()
        interaction.interaction_id = INTERACTION_ID

        deps = {
            "manager_service": MagicMock(
                is_manager_for_order=AsyncMock(return_value=True)
            ),
            "order_repo": MagicMock(get_by_id=AsyncMock(return_value=order)),
            "offer_dispatch_repo": MagicMock(
                get_by_order_and_blogger=AsyncMock(
                    return_value=_make_dispatch()
                )
            ),
            "interaction_service": MagicMock(
                get_or_create=AsyncMock(return_value=interaction)
            ),
        }

        dispatcher = MagicMock()
        dispatcher.__getitem__ = lambda self, k: deps[k]

        request = MagicMock()
        request.app.state.dispatcher = dispatcher

        body = ManagerFeedbackRequest(
            init_data="x", status="issue", issue_description="   "
        )

        with (
            patch(
                "ugc_bot.miniapp.api._ensure_user_and_get_id",
                new=AsyncMock(return_value=MANAGER_ID),
            ),
            pytest.raises(HTTPException) as exc_info,
        ):
            await manager_feedback(request, ORDER_ID, BLOGGER_ID, body)

        assert exc_info.value.status_code == 422

    @pytest.mark.asyncio
    async def test_feedback_issue_notifies_admins(self) -> None:
        order = _make_order()
        interaction = MagicMock()
        interaction.interaction_id = INTERACTION_ID

        updated = MagicMock()
        updated.interaction_id = INTERACTION_ID

        interaction_service = MagicMock(after_feedback_commit=AsyncMock())
        interaction_service.get_or_create = AsyncMock(return_value=interaction)
        interaction_service.record_advertiser_feedback = AsyncMock(
            return_value=updated
        )

        complaint = MagicMock()
        complaint_service = MagicMock()
        complaint_service.get_or_create_for_interaction = AsyncMock(
            return_value=(complaint, True)
        )

        user_role_service = MagicMock()
        messenger_client = MagicMock()

        deps = {
            "manager_service": MagicMock(
                is_manager_for_order=AsyncMock(return_value=True)
            ),
            "order_repo": MagicMock(get_by_id=AsyncMock(return_value=order)),
            "offer_dispatch_repo": MagicMock(
                get_by_order_and_blogger=AsyncMock(
                    return_value=_make_dispatch()
                )
            ),
            "interaction_service": interaction_service,
            "complaint_service": complaint_service,
            "user_role_service": user_role_service,
            "messenger_client": messenger_client,
        }

        dispatcher = MagicMock()
        dispatcher.__getitem__ = lambda self, k: deps[k]

        request = MagicMock()
        request.app.state.dispatcher = dispatcher

        body = ManagerFeedbackRequest(
            init_data="x", status="issue", issue_description="Обман"
        )

        with (
            patch(
                "ugc_bot.miniapp.api._ensure_user_and_get_id",
                new=AsyncMock(return_value=MANAGER_ID),
            ),
            patch(
                "ugc_bot.miniapp.api.notify_admins_about_complaint",
                new=AsyncMock(),
            ) as mock_notify,
        ):
            result = await manager_feedback(request, ORDER_ID, BLOGGER_ID, body)

        assert result["ok"] is True
        mock_notify.assert_awaited_once_with(
            complaint=complaint,
            messenger_client=messenger_client,
            user_role_service=user_role_service,
        )


BLOGGER_ID_2 = UUID("00000000-0000-0000-0000-000000000b21")


def _make_expensive_dispatch() -> OfferDispatch:
    return OfferDispatch(
        order_id=ORDER_ID,
        blogger_id=BLOGGER_ID,
        created_at=datetime.now(timezone.utc),
        in_offer=False,
        accepted=False,
        rejection_reason=RejectionReason.LOW_PRICE,
        desired_price=Decimal("500"),
    )


def _creators_deps(
    dispatches: list[OfferDispatch],
    total: int,
    *,
    expensive: bool = False,
    users: dict | None = None,
) -> dict:
    manager_service = MagicMock()
    manager_service.is_manager_for_order = AsyncMock(return_value=True)
    if expensive:
        manager_service.list_expensive_creators = AsyncMock(
            return_value=(dispatches, total)
        )
    else:
        manager_service.list_creators_for_order = AsyncMock(
            return_value=(dispatches, total)
        )

    if users is None:
        user = MagicMock()
        user.telegram = "blogger_user"
        user.username = "Blogger Name"
        users = {BLOGGER_ID: user}
    user_repo = MagicMock()
    user_repo.get_by_ids = AsyncMock(return_value=users)

    profile = MagicMock()
    profile.instagram_url = "https://instagram.com/blogger"
    profile.phone = None
    profile_service = MagicMock()
    profile_service.get_blogger_profiles = AsyncMock(
        return_value={BLOGGER_ID: profile}
    )

    return {
        "manager_service": manager_service,
        "user_repo": user_repo,
        "profile_service": profile_service,
    }


class TestManagerCreatorsExpensiveFilter:
    """Tests for filter='expensive' in manager_creators."""

    @pytest.mark.asyncio
    async def test_expensive_filter_calls_list_expensive(
        self,
    ) -> None:
        dispatch = _make_expensive_dispatch()
        deps = _creators_deps([dispatch], 1, expensive=True)

        dispatcher = MagicMock()
        dispatcher.__getitem__ = lambda self, k: deps[k]

        request = MagicMock()
        request.app.state.dispatcher = dispatcher

        body = ManagerCreatorsRequest(init_data="x", filter="expensive")

        with patch(
            "ugc_bot.miniapp.api._ensure_user_and_get_id",
            new=AsyncMock(return_value=MANAGER_ID),
        ):
            result = await manager_creators(request, ORDER_ID, body)

        assert result.total == 1
        assert len(result.creators) == 1
        assert result.creators[0].desired_price == 500.0
        deps["manager_service"].list_expensive_creators.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_default_filter_is_in_offer(self) -> None:
        """When both filter and in_offer are None, default to in_offer."""
        dispatch = _make_dispatch()
        deps = _creators_deps([dispatch], 1)

        dispatcher = MagicMock()
        dispatcher.__getitem__ = lambda self, k: deps[k]

        request = MagicMock()
        request.app.state.dispatcher = dispatcher

        body = ManagerCreatorsRequest(init_data="x")

        with patch(
            "ugc_bot.miniapp.api._ensure_user_and_get_id",
            new=AsyncMock(return_value=MANAGER_ID),
        ):
            result = await manager_creators(request, ORDER_ID, body)

        assert result.total == 1
        deps["manager_service"].list_creators_for_order.assert_awaited_once()
        call_kwargs = deps[
            "manager_service"
        ].list_creators_for_order.call_args.kwargs
        assert call_kwargs["in_offer"] is True


class TestManagerCreatorsSearch:
    """Tests for search filtering in manager_creators."""

    @pytest.mark.asyncio
    async def test_search_filters_by_name(self) -> None:
        d1 = _make_dispatch()
        d2 = OfferDispatch(
            order_id=ORDER_ID,
            blogger_id=BLOGGER_ID_2,
            created_at=datetime.now(timezone.utc),
            in_offer=True,
            manager_id=MANAGER_ID,
        )
        user1 = MagicMock()
        user1.telegram = "alice"
        user1.username = "Alice Smith"
        user2 = MagicMock()
        user2.telegram = "bob"
        user2.username = "Bob Jones"
        users = {BLOGGER_ID: user1, BLOGGER_ID_2: user2}

        deps = _creators_deps([d1, d2], 2, users=users)

        profile2 = MagicMock()
        profile2.instagram_url = "https://instagram.com/bob"
        profile2.phone = None
        profile1 = MagicMock(
            instagram_url="https://instagram.com/alice",
            phone=None,
        )
        deps["profile_service"].get_blogger_profiles = AsyncMock(
            return_value={
                BLOGGER_ID: profile1,
                BLOGGER_ID_2: profile2,
            }
        )

        dispatcher = MagicMock()
        dispatcher.__getitem__ = lambda self, k: deps[k]

        request = MagicMock()
        request.app.state.dispatcher = dispatcher

        body = ManagerCreatorsRequest(
            init_data="x", filter="in_offer", search="alice"
        )

        with patch(
            "ugc_bot.miniapp.api._ensure_user_and_get_id",
            new=AsyncMock(return_value=MANAGER_ID),
        ):
            result = await manager_creators(request, ORDER_ID, body)

        assert result.total == 1
        assert len(result.creators) == 1
        assert result.creators[0].name == "Alice Smith"

    @pytest.mark.asyncio
    async def test_search_no_match_returns_empty(self) -> None:
        dispatch = _make_dispatch()
        deps = _creators_deps([dispatch], 1)

        dispatcher = MagicMock()
        dispatcher.__getitem__ = lambda self, k: deps[k]

        request = MagicMock()
        request.app.state.dispatcher = dispatcher

        body = ManagerCreatorsRequest(
            init_data="x",
            filter="in_offer",
            search="nonexistent",
        )

        with patch(
            "ugc_bot.miniapp.api._ensure_user_and_get_id",
            new=AsyncMock(return_value=MANAGER_ID),
        ):
            result = await manager_creators(request, ORDER_ID, body)

        assert result.total == 0
        assert len(result.creators) == 0
