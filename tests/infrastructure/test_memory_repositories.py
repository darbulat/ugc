"""Tests for in-memory repository implementations."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from ugc_bot.domain.entities import (
    Interaction,
    Order,
    Payment,
    PayoutRequest,
    User,
)
from ugc_bot.domain.enums import (
    InteractionStatus,
    MessengerType,
    OrderStatus,
    OrderType,
    PaymentStatus,
    PayoutRequestStatus,
    UserStatus,
)
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryInteractionRepository,
    InMemoryOfferDispatchRepository,
    InMemoryOrderRepository,
    InMemoryPaymentRepository,
    InMemoryPayoutRequestRepository,
    InMemoryUserRepository,
)


@pytest.mark.asyncio
async def test_order_repo_list_active() -> None:
    """list_active returns only ACTIVE orders."""

    repo = InMemoryOrderRepository()
    adv_id = UUID("00000000-0000-0000-0000-000000000001")
    now = datetime.now(timezone.utc)
    await repo.save(
        Order(
            order_id=UUID("00000000-0000-0000-0000-000000000010"),
            advertiser_id=adv_id,
            order_type=OrderType.UGC_ONLY,
            product_link="https://x.com",
            offer_text="Offer",
            barter_description=None,
            price=1000.0,
            bloggers_needed=3,
            status=OrderStatus.ACTIVE,
            created_at=now,
            completed_at=None,
        )
    )
    await repo.save(
        Order(
            order_id=UUID("00000000-0000-0000-0000-000000000011"),
            advertiser_id=adv_id,
            order_type=OrderType.UGC_ONLY,
            product_link="https://x.com",
            offer_text="Offer",
            barter_description=None,
            price=1000.0,
            bloggers_needed=3,
            status=OrderStatus.NEW,
            created_at=now,
            completed_at=None,
        )
    )
    active = list(await repo.list_active())
    assert len(active) == 1
    assert active[0].status == OrderStatus.ACTIVE


@pytest.mark.asyncio
async def test_order_repo_list_completed_before() -> None:
    """list_completed_before returns orders with completed_at before cutoff."""

    repo = InMemoryOrderRepository()
    adv_id = UUID("00000000-0000-0000-0000-000000000002")
    now = datetime.now(timezone.utc)
    cutoff = datetime(2025, 6, 1, tzinfo=timezone.utc)
    await repo.save(
        Order(
            order_id=UUID("00000000-0000-0000-0000-000000000020"),
            advertiser_id=adv_id,
            order_type=OrderType.UGC_ONLY,
            product_link="https://x.com",
            offer_text="Offer",
            barter_description=None,
            price=1000.0,
            bloggers_needed=3,
            status=OrderStatus.CLOSED,
            created_at=now,
            completed_at=datetime(2025, 5, 15, tzinfo=timezone.utc),
        )
    )
    completed = list(await repo.list_completed_before(cutoff))
    assert len(completed) == 1
    assert completed[0].completed_at is not None


@pytest.mark.asyncio
async def test_offer_dispatch_repo_list_responses_by_blogger() -> None:
    """list_responses_by_blogger returns dispatches where blogger responded."""

    repo = InMemoryOfferDispatchRepository()
    order_id = UUID("00000000-0000-0000-0000-000000000030")
    blogger_id = UUID("00000000-0000-0000-0000-000000000031")
    await repo.record_sent(order_id, blogger_id)
    await repo.record_response(
        order_id, blogger_id, accepted=True, in_offer=True
    )
    responses = list(await repo.list_responses_by_blogger(blogger_id))
    assert len(responses) == 1
    assert responses[0].blogger_id == blogger_id


@pytest.mark.asyncio
async def test_offer_dispatch_repo_count_by_order() -> None:
    """count_by_order returns count of dispatches for order."""

    repo = InMemoryOfferDispatchRepository()
    order_id = UUID("00000000-0000-0000-0000-000000000040")
    await repo.record_sent(
        order_id, UUID("00000000-0000-0000-0000-000000000041")
    )
    await repo.record_sent(
        order_id, UUID("00000000-0000-0000-0000-000000000042")
    )
    count = await repo.count_by_order(order_id)
    assert count == 2
    await repo.record_response(
        order_id,
        UUID("00000000-0000-0000-0000-000000000041"),
        accepted=True,
        in_offer=True,
    )
    await repo.record_response(
        order_id,
        UUID("00000000-0000-0000-0000-000000000042"),
        accepted=True,
        in_offer=True,
    )
    accepted_count = await repo.count_accepted_by_order(order_id)
    assert accepted_count == 2


@pytest.mark.asyncio
async def test_offer_dispatch_repo_count_accepted_by_order() -> None:
    """count_accepted_by_order returns count of in_offer=True only."""
    repo = InMemoryOfferDispatchRepository()
    order_id = UUID("00000000-0000-0000-0000-000000000050")
    await repo.record_sent(
        order_id, UUID("00000000-0000-0000-0000-000000000051")
    )
    await repo.record_sent(
        order_id, UUID("00000000-0000-0000-0000-000000000052")
    )
    await repo.record_response(
        order_id,
        UUID("00000000-0000-0000-0000-000000000051"),
        accepted=True,
        in_offer=True,
    )
    await repo.record_response(
        order_id,
        UUID("00000000-0000-0000-0000-000000000052"),
        accepted=True,
        in_offer=False,
    )
    assert await repo.count_by_order(order_id) == 2
    assert await repo.count_accepted_by_order(order_id) == 1


@pytest.mark.asyncio
async def test_interaction_repo_list_blogger_ids_with_unfulfilled() -> None:
    """Unfulfilled interaction blogger_ids (PENDING or ISSUE) returned."""
    now = datetime.now(timezone.utc)
    blogger_pending = UUID("00000000-0000-0000-0000-000000000060")
    blogger_ok = UUID("00000000-0000-0000-0000-000000000061")
    repo = InMemoryInteractionRepository()
    await repo.save(
        Interaction(
            interaction_id=UUID("00000000-0000-0000-0000-000000000062"),
            order_id=UUID("00000000-0000-0000-0000-000000000063"),
            blogger_id=blogger_pending,
            advertiser_id=UUID("00000000-0000-0000-0000-000000000064"),
            status=InteractionStatus.PENDING,
            from_advertiser=None,
            from_blogger=None,
            postpone_count=0,
            next_check_at=None,
            created_at=now,
            updated_at=now,
        )
    )
    await repo.save(
        Interaction(
            interaction_id=UUID("00000000-0000-0000-0000-000000000065"),
            order_id=UUID("00000000-0000-0000-0000-000000000066"),
            blogger_id=blogger_ok,
            advertiser_id=UUID("00000000-0000-0000-0000-000000000067"),
            status=InteractionStatus.OK,
            from_advertiser=None,
            from_blogger=None,
            postpone_count=0,
            next_check_at=None,
            created_at=now,
            updated_at=now,
        )
    )
    result = await repo.list_blogger_ids_with_unfulfilled_interaction()
    assert blogger_pending in result
    assert blogger_ok not in result


# ---------------------------------------------------------------------------
# InMemoryUserRepository.get_by_telegram — empty/blank input returns None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_user_repo_get_by_telegram_returns_none_for_empty_string() -> (
    None
):
    """get_by_telegram returns None when the telegram argument is empty."""
    repo = InMemoryUserRepository()
    now = datetime.now(timezone.utc)
    await repo.save(
        User(
            user_id=uuid4(),
            external_id="100",
            messenger_type=MessengerType.TELEGRAM,
            username="testuser",
            status=UserStatus.ACTIVE,
            issue_count=0,
            created_at=now,
            telegram="@someuser",
        )
    )
    # Empty string, whitespace, and "@"-only should all return None
    assert await repo.get_by_telegram("") is None
    assert await repo.get_by_telegram("   ") is None
    assert await repo.get_by_telegram("@") is None


@pytest.mark.asyncio
async def test_user_repo_get_by_telegram_finds_user_case_insensitive() -> None:
    """get_by_telegram matches case-insensitively and strips the @ prefix."""
    repo = InMemoryUserRepository()
    now = datetime.now(timezone.utc)
    user_id = uuid4()
    await repo.save(
        User(
            user_id=user_id,
            external_id="101",
            messenger_type=MessengerType.TELEGRAM,
            username="testuser",
            status=UserStatus.ACTIVE,
            issue_count=0,
            created_at=now,
            telegram="@MyHandle",
        )
    )
    found = await repo.get_by_telegram("@myhandle")
    assert found is not None
    assert found.user_id == user_id

    found2 = await repo.get_by_telegram("MYHANDLE")
    assert found2 is not None
    assert found2.user_id == user_id


# ---------------------------------------------------------------------------
# InMemoryPayoutRequestRepository.update_status — request not found → False
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_payout_repo_update_status_returns_false_when_not_found() -> None:
    """update_status returns False when the request_id does not exist."""
    repo = InMemoryPayoutRequestRepository()
    missing_id = uuid4()
    result = await repo.update_status(missing_id, PayoutRequestStatus.PAID)
    assert result is False


@pytest.mark.asyncio
async def test_payout_repo_update_status_returns_true_and_updates() -> None:
    """update_status returns True and updates status when request exists."""
    repo = InMemoryPayoutRequestRepository()
    request_id = uuid4()
    user_id = uuid4()
    now = datetime.now(timezone.utc)
    request = PayoutRequest(
        request_id=request_id,
        user_id=user_id,
        requested_at=now,
        status=PayoutRequestStatus.PENDING,
    )
    await repo.save(request)
    result = await repo.update_status(request_id, PayoutRequestStatus.PAID)
    assert result is True
    updated = await repo.get_by_id(request_id)
    assert updated is not None
    assert updated.status == PayoutRequestStatus.PAID


# ---------------------------------------------------------------------------
# InMemoryOfferDispatchRepository.count_completed_orders_by_blogger_ids
# covers lines 687 (not in_offer) and 692 (order is None / status != CLOSED)
# ---------------------------------------------------------------------------


def _make_order(
    order_id: UUID,
    advertiser_id: UUID,
    status: OrderStatus,
) -> Order:
    now = datetime.now(timezone.utc)
    return Order(
        order_id=order_id,
        advertiser_id=advertiser_id,
        order_type=OrderType.UGC_ONLY,
        product_link="https://x.com",
        offer_text="Offer",
        barter_description=None,
        price=1000.0,
        bloggers_needed=3,
        status=status,
        created_at=now,
    )


def _make_interaction(
    interaction_id: UUID,
    order_id: UUID,
    blogger_id: UUID,
    advertiser_id: UUID,
    status: InteractionStatus,
) -> Interaction:
    now = datetime.now(timezone.utc)
    return Interaction(
        interaction_id=interaction_id,
        order_id=order_id,
        blogger_id=blogger_id,
        advertiser_id=advertiser_id,
        status=status,
        from_advertiser=None,
        from_blogger=None,
        postpone_count=0,
        next_check_at=None,
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_count_completed_skips_dispatch_not_in_offer() -> None:
    """count_completed_orders_by_blogger_ids skips when in_offer=False."""
    order_repo = InMemoryOrderRepository()
    interaction_repo = InMemoryInteractionRepository()
    dispatch_repo = InMemoryOfferDispatchRepository(
        order_repo=order_repo, interaction_repo=interaction_repo
    )

    blogger_id = uuid4()
    advertiser_id = uuid4()
    order_id = uuid4()

    await order_repo.save(
        _make_order(order_id, advertiser_id, OrderStatus.CLOSED)
    )
    await dispatch_repo.record_sent(order_id, blogger_id)
    # Record response with in_offer=False — should be skipped by count
    await dispatch_repo.record_response(
        order_id, blogger_id, accepted=True, in_offer=False
    )

    result = await dispatch_repo.count_completed_orders_by_blogger_ids(
        [blogger_id]
    )
    assert result[blogger_id] == 0


@pytest.mark.asyncio
async def test_count_completed_skips_order_with_wrong_status() -> None:
    """count_completed_orders_by_blogger_ids skips when status not CLOSED."""
    order_repo = InMemoryOrderRepository()
    interaction_repo = InMemoryInteractionRepository()
    dispatch_repo = InMemoryOfferDispatchRepository(
        order_repo=order_repo, interaction_repo=interaction_repo
    )

    blogger_id = uuid4()
    advertiser_id = uuid4()
    order_id = uuid4()

    # Order is ACTIVE, not CLOSED
    await order_repo.save(
        _make_order(order_id, advertiser_id, OrderStatus.ACTIVE)
    )
    await dispatch_repo.record_sent(order_id, blogger_id)
    await dispatch_repo.record_response(
        order_id, blogger_id, accepted=True, in_offer=True
    )

    result = await dispatch_repo.count_completed_orders_by_blogger_ids(
        [blogger_id]
    )
    assert result[blogger_id] == 0


@pytest.mark.asyncio
async def test_count_completed_skips_missing_order() -> None:
    """count_completed_orders_by_blogger_ids skips when order is None."""
    order_repo = InMemoryOrderRepository()
    interaction_repo = InMemoryInteractionRepository()
    dispatch_repo = InMemoryOfferDispatchRepository(
        order_repo=order_repo, interaction_repo=interaction_repo
    )

    blogger_id = uuid4()
    order_id = uuid4()  # never saved to order_repo

    await dispatch_repo.record_sent(order_id, blogger_id)
    await dispatch_repo.record_response(
        order_id, blogger_id, accepted=True, in_offer=True
    )

    result = await dispatch_repo.count_completed_orders_by_blogger_ids(
        [blogger_id]
    )
    assert result[blogger_id] == 0


# ---------------------------------------------------------------------------
# InMemoryInteractionRepository.list_by_status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_interaction_repo_list_by_status() -> None:
    """list_by_status returns only interactions matching the given status."""
    repo = InMemoryInteractionRepository()
    blogger_a = uuid4()
    blogger_b = uuid4()
    advertiser = uuid4()
    order_id = uuid4()

    await repo.save(
        _make_interaction(
            uuid4(), order_id, blogger_a, advertiser, InteractionStatus.PENDING
        )
    )
    await repo.save(
        _make_interaction(
            uuid4(), order_id, blogger_b, advertiser, InteractionStatus.OK
        )
    )

    pending = list(await repo.list_by_status(InteractionStatus.PENDING))
    assert len(pending) == 1
    assert pending[0].blogger_id == blogger_a

    ok_list = list(await repo.list_by_status(InteractionStatus.OK))
    assert len(ok_list) == 1
    assert ok_list[0].blogger_id == blogger_b


# ---------------------------------------------------------------------------
# InMemoryInteractionRepository.update_next_check_at
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_interaction_repo_update_next_check_at_when_exists() -> None:
    """update_next_check_at updates next_check_at when interaction is found."""
    repo = InMemoryInteractionRepository()
    interaction_id = uuid4()
    order_id = uuid4()
    blogger_id = uuid4()
    advertiser_id = uuid4()

    await repo.save(
        _make_interaction(
            interaction_id,
            order_id,
            blogger_id,
            advertiser_id,
            InteractionStatus.PENDING,
        )
    )

    new_check_at = datetime(2030, 1, 1, tzinfo=timezone.utc)
    await repo.update_next_check_at(interaction_id, new_check_at)

    updated = await repo.get_by_id(interaction_id)
    assert updated is not None
    assert updated.next_check_at == new_check_at


@pytest.mark.asyncio
async def test_interaction_repo_update_next_check_at_when_missing_is_noop() -> (
    None
):
    """update_next_check_at is a no-op when interaction does not exist."""
    repo = InMemoryInteractionRepository()
    missing_id = uuid4()
    new_check_at = datetime(2030, 1, 1, tzinfo=timezone.utc)
    # Should not raise
    await repo.update_next_check_at(missing_id, new_check_at)
    result = await repo.get_by_id(missing_id)
    assert result is None


# ---------------------------------------------------------------------------
# InMemoryPaymentRepository.get_by_external_id — payment found
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_payment_repo_get_by_external_id_returns_payment_when_found() -> (
    None
):
    """get_by_external_id returns the payment matching the external_id."""
    repo = InMemoryPaymentRepository()
    now = datetime.now(timezone.utc)
    payment_id = uuid4()
    order_id = uuid4()
    payment = Payment(
        payment_id=payment_id,
        order_id=order_id,
        provider="yookassa",
        status=PaymentStatus.PENDING,
        amount=5000.0,
        currency="RUB",
        external_id="ext-abc-123",
        created_at=now,
    )
    await repo.save(payment)

    found = await repo.get_by_external_id("ext-abc-123")
    assert found is not None
    assert found.payment_id == payment_id
    assert found.external_id == "ext-abc-123"


@pytest.mark.asyncio
async def test_payment_repo_get_by_external_id_returns_none_when_not_found() -> (  # noqa: E501
    None
):
    """get_by_external_id returns None when no payment has that external_id."""
    repo = InMemoryPaymentRepository()
    found = await repo.get_by_external_id("nonexistent")
    assert found is None


@pytest.mark.asyncio
async def test_in_memory_country_repository_list_enabled() -> None:
    """list_enabled returns only enabled countries."""
    from ugc_bot.domain.entities import Country
    from ugc_bot.infrastructure.memory_repositories import (
        InMemoryCountryRepository,
    )

    repo = InMemoryCountryRepository(
        countries={
            "ru": Country(
                code="ru",
                name_native="Россия",
                currency_code="RUB",
                currency_symbol="₽",
                enabled=True,
            ),
            "xx": Country(
                code="xx",
                name_native="Disabled",
                currency_code="XXX",
                currency_symbol="X",
                enabled=False,
            ),
        }
    )
    enabled = await repo.list_enabled()
    assert len(enabled) == 1
    assert enabled[0].code == "ru"


@pytest.mark.asyncio
async def test_in_memory_country_repository_get_by_code() -> None:
    """get_by_code returns country when found, None otherwise."""
    from ugc_bot.domain.entities import Country
    from ugc_bot.infrastructure.memory_repositories import (
        InMemoryCountryRepository,
    )

    ru = Country(
        code="ru",
        name_native="Россия",
        currency_code="RUB",
        currency_symbol="₽",
    )
    repo = InMemoryCountryRepository(countries={"ru": ru})
    found = await repo.get_by_code("ru")
    assert found is not None
    assert found.code == "ru"
    assert await repo.get_by_code("zz") is None


# ---------- BotTextsRepository ----------


@pytest.mark.asyncio
async def test_in_memory_bot_texts_repo_get() -> None:
    from ugc_bot.infrastructure.memory_repositories import (
        InMemoryBotTextsRepository,
    )

    repo = InMemoryBotTextsRepository(_texts={("greeting", "ru"): "Привет"})
    assert await repo.get("greeting", "ru") == "Привет"
    assert await repo.get("greeting", "en") is None
    assert await repo.get("missing", "ru") is None


@pytest.mark.asyncio
async def test_in_memory_bot_texts_repo_get_all() -> None:
    from ugc_bot.infrastructure.memory_repositories import (
        InMemoryBotTextsRepository,
    )

    repo = InMemoryBotTextsRepository(
        _texts={("k1", "ru"): "v1", ("k2", "en"): "v2"}
    )
    rows = await repo.get_all()
    assert len(rows) == 2
    assert ("k1", "ru", "v1") in rows
    assert ("k2", "en", "v2") in rows
