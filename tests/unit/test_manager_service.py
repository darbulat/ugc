"""Unit tests for ManagerService."""

from dataclasses import replace
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from ugc_bot.application.services.manager_service import ManagerService
from ugc_bot.domain.entities import OfferDispatch, Order, User
from ugc_bot.domain.enums import (
    MessengerType,
    OrderStatus,
    OrderType,
    UserStatus,
)
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryManagerOrderRepository,
    InMemoryOfferDispatchRepository,
    InMemoryOrderRepository,
    InMemoryUserRepository,
)


def _make_user(telegram: str | None = None) -> User:
    """Create a minimal User entity for testing."""
    return User(
        user_id=uuid4(),
        telegram_id=str(uuid4()),
        messenger_type=MessengerType.TELEGRAM,
        username=telegram or "testuser",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        telegram=telegram,
    )


def _make_order() -> Order:
    """Create a minimal Order entity for testing."""
    return Order(
        order_id=uuid4(),
        advertiser_id=uuid4(),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Test offer",
        barter_description="Test barter",
        price=0.0,
        bloggers_needed=1,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
    )


def _build_service() -> tuple[
    ManagerService,
    InMemoryManagerOrderRepository,
    InMemoryUserRepository,
    InMemoryOrderRepository,
]:
    """Build ManagerService with in-memory repos."""
    manager_order_repo = InMemoryManagerOrderRepository()
    user_repo = InMemoryUserRepository()
    order_repo = InMemoryOrderRepository()
    svc = ManagerService(
        manager_order_repo=manager_order_repo,
        user_repo=user_repo,
        order_repo=order_repo,
    )
    return svc, manager_order_repo, user_repo, order_repo


@pytest.mark.asyncio
async def test_set_managers_for_order_success():
    """set_managers_for_order persists assignments for valid usernames."""
    svc, manager_order_repo, user_repo, _ = _build_service()
    user_a = _make_user(telegram="alice")
    user_b = _make_user(telegram="bob")
    await user_repo.save(user_a)
    await user_repo.save(user_b)
    order = _make_order()

    await svc.set_managers_for_order(order.order_id, ["@alice", "bob"])

    managers = await manager_order_repo.list_by_order(order.order_id)
    assert len(managers) == 2
    ids = {m.user_id for m in managers}
    assert ids == {user_a.user_id, user_b.user_id}


@pytest.mark.asyncio
async def test_set_managers_for_order_username_not_found():
    """Raises ManagerUserNotFoundError when username not in DB."""
    svc, _, _, _ = _build_service()
    order = _make_order()

    with pytest.raises(ValueError, match="@missing"):
        await svc.set_managers_for_order(order.order_id, ["@missing"])


@pytest.mark.asyncio
async def test_set_managers_for_order_replaces_existing():
    """Calling set_managers_for_order twice replaces previous assignments."""
    svc, manager_order_repo, user_repo, _ = _build_service()
    user_a = _make_user(telegram="alice")
    user_b = _make_user(telegram="bob")
    await user_repo.save(user_a)
    await user_repo.save(user_b)
    order = _make_order()

    await svc.set_managers_for_order(order.order_id, ["@alice", "@bob"])
    # Replace with only bob
    await svc.set_managers_for_order(order.order_id, ["@bob"])

    managers = await manager_order_repo.list_by_order(order.order_id)
    assert len(managers) == 1
    assert managers[0].user_id == user_b.user_id


@pytest.mark.asyncio
async def test_set_managers_for_order_skips_empty_usernames():
    """Empty/whitespace-only usernames are silently skipped."""
    svc, manager_order_repo, user_repo, _ = _build_service()
    user_a = _make_user(telegram="alice")
    await user_repo.save(user_a)
    order = _make_order()

    await svc.set_managers_for_order(order.order_id, ["  ", "@alice", ""])

    managers = await manager_order_repo.list_by_order(order.order_id)
    assert len(managers) == 1


@pytest.mark.asyncio
async def test_get_next_manager_id_round_robin():
    """Round-robin cycles through managers: 0->A, 1->B, 2->C, 3->A."""
    svc, manager_order_repo, user_repo, _ = _build_service()
    users = [_make_user(telegram=name) for name in ("alice", "bob", "carol")]
    for u in users:
        await user_repo.save(u)
    order = _make_order()

    await svc.set_managers_for_order(order.order_id, ["alice", "bob", "carol"])

    managers = await manager_order_repo.list_by_order(order.order_id)
    expected_ids = [m.user_id for m in managers]

    # index 0 -> first manager
    result = await svc.get_next_manager_id(order)
    assert result == expected_ids[0]

    # index 1 -> second manager
    order1 = replace(order, last_round_robin_index=1)
    result = await svc.get_next_manager_id(order1)
    assert result == expected_ids[1]

    # index 2 -> third manager
    order2 = replace(order, last_round_robin_index=2)
    result = await svc.get_next_manager_id(order2)
    assert result == expected_ids[2]

    # index 3 -> wraps back to first manager
    order3 = replace(order, last_round_robin_index=3)
    result = await svc.get_next_manager_id(order3)
    assert result == expected_ids[0]


@pytest.mark.asyncio
async def test_get_next_manager_id_no_managers():
    """get_next_manager_id returns None when no managers assigned."""
    svc, _, _, _ = _build_service()
    order = _make_order()

    result = await svc.get_next_manager_id(order)
    assert result is None


@pytest.mark.asyncio
async def test_is_manager_false_then_true():
    """is_manager returns False when user has no assignments, True after."""
    svc, _, user_repo, _ = _build_service()
    user = _make_user(telegram="alice")
    await user_repo.save(user)

    assert await svc.is_manager(user.user_id) is False

    order = _make_order()
    await svc.set_managers_for_order(order.order_id, ["alice"])

    assert await svc.is_manager(user.user_id) is True


@pytest.mark.asyncio
async def test_list_orders_for_manager():
    """list_orders_for_manager returns orders and total count."""
    svc, _, user_repo, order_repo = _build_service()
    user = _make_user(telegram="alice")
    await user_repo.save(user)

    orders = [_make_order() for _ in range(3)]
    for o in orders:
        await order_repo.save(o)
        await svc.set_managers_for_order(o.order_id, ["alice"])

    result_orders, total = await svc.list_orders_for_manager(
        user.user_id, limit=2, offset=0
    )
    assert total == 3
    assert len(result_orders) == 2


@pytest.mark.asyncio
async def test_list_orders_for_manager_empty():
    """list_orders_for_manager returns empty list when no assignments."""
    svc, _, _, _ = _build_service()
    result_orders, total = await svc.list_orders_for_manager(uuid4())
    assert total == 0
    assert result_orders == []


@pytest.mark.asyncio
async def test_is_manager_for_order_true():
    """is_manager_for_order returns True when user is assigned to order."""
    svc, _, user_repo, _ = _build_service()
    user = _make_user(telegram="alice")
    await user_repo.save(user)
    order = _make_order()
    await svc.set_managers_for_order(order.order_id, ["alice"])

    result = await svc.is_manager_for_order(user.user_id, order.order_id)
    assert result is True


@pytest.mark.asyncio
async def test_is_manager_for_order_false_different_order():
    """is_manager_for_order returns False when user assigned to other order."""
    svc, _, user_repo, _ = _build_service()
    user = _make_user(telegram="alice")
    await user_repo.save(user)
    order = _make_order()
    await svc.set_managers_for_order(order.order_id, ["alice"])

    other_order_id = uuid4()
    result = await svc.is_manager_for_order(user.user_id, other_order_id)
    assert result is False


@pytest.mark.asyncio
async def test_is_manager_for_order_false_no_assignments():
    """is_manager_for_order returns False when order has no managers."""
    svc, _, _, _ = _build_service()
    result = await svc.is_manager_for_order(uuid4(), uuid4())
    assert result is False


@pytest.mark.asyncio
async def test_list_creators_for_order_no_dispatch_repo():
    """list_creators_for_order returns empty when no dispatch repo."""
    svc, _, _, _ = _build_service()
    assert svc.offer_dispatch_repo is None
    dispatches, total = await svc.list_creators_for_order(
        order_id=uuid4(),
        manager_id=uuid4(),
        in_offer=True,
    )
    assert dispatches == []
    assert total == 0


@pytest.mark.asyncio
async def test_list_creators_for_order_in_offer_filters_by_manager():
    """list_creators_for_order with in_offer=True filters by manager_id."""
    manager_order_repo = InMemoryManagerOrderRepository()
    user_repo = InMemoryUserRepository()
    order_repo = InMemoryOrderRepository()
    dispatch_repo = InMemoryOfferDispatchRepository()
    svc = ManagerService(
        manager_order_repo=manager_order_repo,
        user_repo=user_repo,
        order_repo=order_repo,
        offer_dispatch_repo=dispatch_repo,
    )

    order_id = uuid4()
    manager_id = uuid4()
    blogger_id = uuid4()
    now = datetime.now(timezone.utc)
    dispatch = OfferDispatch(
        order_id=order_id,
        blogger_id=blogger_id,
        created_at=now,
        accepted=True,
        in_offer=True,
        manager_id=manager_id,
    )
    dispatch_repo._dispatches[blogger_id] = dispatch

    dispatches, total = await svc.list_creators_for_order(
        order_id=order_id,
        manager_id=manager_id,
        in_offer=True,
    )
    assert total == 1
    assert len(dispatches) == 1
    assert dispatches[0].blogger_id == blogger_id


@pytest.mark.asyncio
async def test_list_creators_for_order_not_in_offer_ignores_manager():
    """list_creators_for_order with in_offer=False returns all dispatches."""
    manager_order_repo = InMemoryManagerOrderRepository()
    user_repo = InMemoryUserRepository()
    order_repo = InMemoryOrderRepository()
    dispatch_repo = InMemoryOfferDispatchRepository()
    svc = ManagerService(
        manager_order_repo=manager_order_repo,
        user_repo=user_repo,
        order_repo=order_repo,
        offer_dispatch_repo=dispatch_repo,
    )

    order_id = uuid4()
    manager_a = uuid4()
    manager_b = uuid4()
    now = datetime.now(timezone.utc)
    # Two dispatches with different managers, both not in_offer
    for mid, bid in [(manager_a, uuid4()), (manager_b, uuid4())]:
        d = OfferDispatch(
            order_id=order_id,
            blogger_id=bid,
            created_at=now,
            accepted=True,
            in_offer=False,
            manager_id=mid,
        )
        dispatch_repo._dispatches[bid] = d

    dispatches, total = await svc.list_creators_for_order(
        order_id=order_id,
        manager_id=manager_a,
        in_offer=False,
    )
    assert total == 2
    assert len(dispatches) == 2
