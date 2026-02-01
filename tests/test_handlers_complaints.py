"""Tests for complaints handler."""

from datetime import datetime, timezone
from uuid import UUID

import pytest

from ugc_bot.application.services.complaint_service import ComplaintService
from ugc_bot.application.services.offer_response_service import OfferResponseService
from ugc_bot.application.services.order_service import OrderService
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.bot.handlers.complaints import (
    handle_complaint_reason,
    handle_complaint_reason_text,
    select_complaint_target,
    start_complaint,
)
from ugc_bot.domain.entities import Order, OrderResponse, User
from ugc_bot.domain.enums import MessengerType, OrderStatus, OrderType, UserStatus
from tests.helpers.fakes import FakeCallback, FakeMessage, FakeUser
from tests.helpers.factories import create_test_order, create_test_user
from tests.helpers.services import build_order_service


@pytest.mark.asyncio
async def test_start_complaint_invalid_format(
    fake_tm: object, user_repo, order_repo, order_response_repo, advertiser_repo
) -> None:
    """Reject malformed callback data."""

    user_service = UserRoleService(user_repo=user_repo)
    order_service = build_order_service(user_repo, advertiser_repo, order_repo, fake_tm)
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        response_repo=order_response_repo,
        transaction_manager=fake_tm,
    )

    from aiogram.fsm.storage.memory import MemoryStorage
    from aiogram.fsm.context import FSMContext

    storage = MemoryStorage()
    state = FSMContext(storage=storage, key="test")

    from uuid import UUID

    await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000950"),
        external_id="1",
        username="user",
    )

    callback = FakeCallback(data="complaint:bad", user=FakeUser(1))
    await start_complaint(
        callback, state, user_service, order_service, offer_response_service
    )

    assert any("Неверный формат" in ans for ans in callback.answers)


@pytest.mark.asyncio
async def test_start_complaint_order_not_found(
    fake_tm: object, user_repo, order_repo, order_response_repo, advertiser_repo
) -> None:
    """Reject complaint for non-existent order."""

    from uuid import UUID

    await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000951"),
        external_id="1",
        username="user",
    )

    user_service = UserRoleService(user_repo=user_repo)
    order_service = build_order_service(user_repo, advertiser_repo, order_repo, fake_tm)
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        response_repo=order_response_repo,
        transaction_manager=fake_tm,
    )

    from aiogram.fsm.storage.memory import MemoryStorage
    from aiogram.fsm.context import FSMContext

    storage = MemoryStorage()
    state = FSMContext(storage=storage, key="test")

    callback = FakeCallback(
        data=f"complaint:{UUID('00000000-0000-0000-0000-000000000999')}:{UUID('00000000-0000-0000-0000-000000000998')}",
        user=FakeUser(1),
    )
    await start_complaint(
        callback, state, user_service, order_service, offer_response_service
    )

    assert any("Заказ не найден" in ans for ans in callback.answers)


@pytest.mark.asyncio
async def test_start_complaint_no_access(
    fake_tm: object, user_repo, order_repo, order_response_repo, advertiser_repo
) -> None:
    """Reject complaint when user has no access to order."""

    from uuid import UUID

    advertiser = await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000961"),
        external_id="1",
        username="advertiser",
    )
    await create_test_user(
        user_repo,
        user_id=UUID("00000000-0000-0000-0000-000000000962"),
        external_id="2",
        username="other",
    )

    order = await create_test_order(
        order_repo,
        advertiser.user_id,
        order_id=UUID("00000000-0000-0000-0000-000000000963"),
        price=1000.0,
        bloggers_needed=3,
        status=OrderStatus.ACTIVE,
    )

    user_service = UserRoleService(user_repo=user_repo)
    order_service = build_order_service(user_repo, advertiser_repo, order_repo, fake_tm)
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        response_repo=order_response_repo,
        transaction_manager=fake_tm,
    )

    from aiogram.fsm.storage.memory import MemoryStorage
    from aiogram.fsm.context import FSMContext

    storage = MemoryStorage()
    state = FSMContext(storage=storage, key="test")

    callback = FakeCallback(
        data=f"complaint:{order.order_id}:{advertiser.user_id}",
        user=FakeUser(2),
    )
    await start_complaint(
        callback, state, user_service, order_service, offer_response_service
    )

    assert any("нет доступа" in ans.lower() for ans in callback.answers)


@pytest.mark.asyncio
async def test_handle_complaint_reason_success(
    fake_tm: object,
    user_repo,
    order_repo,
    order_response_repo,
    advertiser_repo,
    complaint_repo,
) -> None:
    """Successfully create complaint with selected reason."""

    advertiser = User(
        user_id=UUID("00000000-0000-0000-0000-000000000971"),
        external_id="1",
        messenger_type=MessengerType.TELEGRAM,
        username="advertiser",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    blogger = User(
        user_id=UUID("00000000-0000-0000-0000-000000000972"),
        external_id="2",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(advertiser)
    await user_repo.save(blogger)

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000973"),
        advertiser_id=advertiser.user_id,
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        ugc_requirements=None,
        barter_description=None,
        price=1000.0,
        bloggers_needed=3,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        contacts_sent_at=None,
    )
    await order_repo.save(order)

    await order_response_repo.save(
        OrderResponse(
            response_id=UUID("00000000-0000-0000-0000-000000000974"),
            order_id=order.order_id,
            blogger_id=blogger.user_id,
            responded_at=datetime.now(timezone.utc),
        )
    )

    order_service = build_order_service(user_repo, advertiser_repo, order_repo, fake_tm)
    complaint_service = ComplaintService(complaint_repo=complaint_repo)

    from aiogram.fsm.storage.memory import MemoryStorage
    from aiogram.fsm.context import FSMContext

    storage = MemoryStorage()
    state = FSMContext(storage=storage, key="test")
    await state.update_data(
        order_id=str(order.order_id),
        reported_id=str(advertiser.user_id),
        reporter_id=str(blogger.user_id),
    )

    callback = FakeCallback(data="complaint_reason:Мошенничество", user=FakeUser(2))
    await handle_complaint_reason(callback, state, complaint_service, order_service)

    assert any("успешно подана" in ans for ans in callback.message.answers)
    complaints = await complaint_service.list_by_order(order.order_id)
    assert len(list(complaints)) == 1


@pytest.mark.asyncio
async def test_select_complaint_target_advertiser(
    fake_tm: object,
    user_repo,
    order_repo,
    order_response_repo,
    advertiser_repo,
    complaint_repo,
) -> None:
    """Advertiser can select blogger to complain about."""

    advertiser = User(
        user_id=UUID("00000000-0000-0000-0000-000000000981"),
        external_id="1",
        messenger_type=MessengerType.TELEGRAM,
        username="advertiser",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    blogger = User(
        user_id=UUID("00000000-0000-0000-0000-000000000982"),
        external_id="2",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(advertiser)
    await user_repo.save(blogger)

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000983"),
        advertiser_id=advertiser.user_id,
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        ugc_requirements=None,
        barter_description=None,
        price=1000.0,
        bloggers_needed=3,
        status=OrderStatus.CLOSED,
        created_at=datetime.now(timezone.utc),
        contacts_sent_at=datetime.now(timezone.utc),
    )
    await order_repo.save(order)

    await order_response_repo.save(
        OrderResponse(
            response_id=UUID("00000000-0000-0000-0000-000000000984"),
            order_id=order.order_id,
            blogger_id=blogger.user_id,
            responded_at=datetime.now(timezone.utc),
        )
    )

    user_service = UserRoleService(user_repo=user_repo)
    order_service = build_order_service(user_repo, advertiser_repo, order_repo, fake_tm)
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        response_repo=order_response_repo,
        transaction_manager=fake_tm,
    )

    from aiogram.fsm.storage.memory import MemoryStorage
    from aiogram.fsm.context import FSMContext

    storage = MemoryStorage()
    state = FSMContext(storage=storage, key="test")

    callback = FakeCallback(data=f"complaint_select:{order.order_id}", user=FakeUser(1))
    await select_complaint_target(
        callback,
        state,
        user_service,
        order_service,
        offer_response_service,
        None,  # profile_service not used
    )

    assert callback.message.answers

    def _answer_text(a: str | tuple) -> str:
        return a if isinstance(a, str) else a[0]

    assert any(
        "Выберите блогера" in _answer_text(ans) for ans in callback.message.answers
    )


@pytest.mark.asyncio
async def test_select_complaint_target_invalid_format(
    fake_tm: object,
    user_repo,
    order_repo,
    order_response_repo,
    advertiser_repo,
    complaint_repo,
) -> None:
    """Reject invalid callback format."""

    user = User(
        user_id=UUID("00000000-0000-0000-0000-000000000980"),
        external_id="1",
        messenger_type=MessengerType.TELEGRAM,
        username="user",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(user)

    user_service = UserRoleService(user_repo=user_repo)
    order_service = build_order_service(user_repo, advertiser_repo, order_repo, fake_tm)
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        response_repo=order_response_repo,
        transaction_manager=fake_tm,
    )

    from aiogram.fsm.storage.memory import MemoryStorage
    from aiogram.fsm.context import FSMContext

    storage = MemoryStorage()
    state = FSMContext(storage=storage, key="test")

    callback = FakeCallback(data="complaint_select:bad:format", user=FakeUser(1))
    await select_complaint_target(
        callback,
        state,
        user_service,
        order_service,
        offer_response_service,
        None,
    )

    assert any("Неверный формат" in ans for ans in callback.answers)


@pytest.mark.asyncio
async def test_select_complaint_target_blogger(
    fake_tm: object,
    user_repo,
    order_repo,
    order_response_repo,
    advertiser_repo,
    complaint_repo,
) -> None:
    """Blogger can complain about advertiser."""

    advertiser = User(
        user_id=UUID("00000000-0000-0000-0000-000000000985"),
        external_id="1",
        messenger_type=MessengerType.TELEGRAM,
        username="advertiser",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    blogger = User(
        user_id=UUID("00000000-0000-0000-0000-000000000986"),
        external_id="2",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(advertiser)
    await user_repo.save(blogger)

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000987"),
        advertiser_id=advertiser.user_id,
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        ugc_requirements=None,
        barter_description=None,
        price=1000.0,
        bloggers_needed=3,
        status=OrderStatus.CLOSED,
        created_at=datetime.now(timezone.utc),
        contacts_sent_at=datetime.now(timezone.utc),
    )
    await order_repo.save(order)

    await order_response_repo.save(
        OrderResponse(
            response_id=UUID("00000000-0000-0000-0000-000000000988"),
            order_id=order.order_id,
            blogger_id=blogger.user_id,
            responded_at=datetime.now(timezone.utc),
        )
    )

    user_service = UserRoleService(user_repo=user_repo)
    order_service = build_order_service(user_repo, advertiser_repo, order_repo, fake_tm)
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        response_repo=order_response_repo,
        transaction_manager=fake_tm,
    )

    from aiogram.fsm.storage.memory import MemoryStorage
    from aiogram.fsm.context import FSMContext

    storage = MemoryStorage()
    state = FSMContext(storage=storage, key="test")

    callback = FakeCallback(data=f"complaint_select:{order.order_id}", user=FakeUser(2))
    await select_complaint_target(
        callback,
        state,
        user_service,
        order_service,
        offer_response_service,
        None,  # profile_service not used
    )

    assert callback.message.answers

    def _answer_text(a: str | tuple) -> str:
        return a if isinstance(a, str) else a[0]

    assert any(
        "Выберите причину" in _answer_text(ans) for ans in callback.message.answers
    )


@pytest.mark.asyncio
async def test_select_complaint_target_no_bloggers(
    fake_tm: object,
    user_repo,
    order_repo,
    order_response_repo,
    advertiser_repo,
    complaint_repo,
) -> None:
    """Show message when no bloggers responded."""

    advertiser = User(
        user_id=UUID("00000000-0000-0000-0000-000000000989"),
        external_id="1",
        messenger_type=MessengerType.TELEGRAM,
        username="advertiser",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(advertiser)

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000990"),
        advertiser_id=advertiser.user_id,
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        ugc_requirements=None,
        barter_description=None,
        price=1000.0,
        bloggers_needed=3,
        status=OrderStatus.CLOSED,
        created_at=datetime.now(timezone.utc),
        contacts_sent_at=datetime.now(timezone.utc),
    )
    await order_repo.save(order)

    user_service = UserRoleService(user_repo=user_repo)
    order_service = build_order_service(user_repo, advertiser_repo, order_repo, fake_tm)
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        response_repo=order_response_repo,
        transaction_manager=fake_tm,
    )

    from aiogram.fsm.storage.memory import MemoryStorage
    from aiogram.fsm.context import FSMContext

    storage = MemoryStorage()
    state = FSMContext(storage=storage, key="test")

    callback = FakeCallback(data=f"complaint_select:{order.order_id}", user=FakeUser(1))
    await select_complaint_target(
        callback,
        state,
        user_service,
        order_service,
        offer_response_service,
        None,
    )

    assert any("Нет блогеров" in ans for ans in callback.answers)


@pytest.mark.asyncio
async def test_handle_complaint_reason_text(
    fake_tm: object,
    user_repo,
    order_repo,
    order_response_repo,
    advertiser_repo,
    complaint_repo,
) -> None:
    """Handle text input for complaint reason."""

    advertiser = User(
        user_id=UUID("00000000-0000-0000-0000-000000000991"),
        external_id="1",
        messenger_type=MessengerType.TELEGRAM,
        username="advertiser",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    blogger = User(
        user_id=UUID("00000000-0000-0000-0000-000000000992"),
        external_id="2",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(advertiser)
    await user_repo.save(blogger)

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000993"),
        advertiser_id=advertiser.user_id,
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        ugc_requirements=None,
        barter_description=None,
        price=1000.0,
        bloggers_needed=3,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        contacts_sent_at=None,
    )
    await order_repo.save(order)

    complaint_service = ComplaintService(complaint_repo=complaint_repo)

    from aiogram.fsm.storage.memory import MemoryStorage
    from aiogram.fsm.context import FSMContext

    storage = MemoryStorage()
    state = FSMContext(storage=storage, key="test")
    await state.update_data(
        order_id=str(order.order_id),
        reported_id=str(advertiser.user_id),
        reporter_id=str(blogger.user_id),
        reason="Другое",
    )

    message = FakeMessage(user=FakeUser(2))
    message.text = "Подробное описание проблемы"

    await handle_complaint_reason_text(message, state, complaint_service)

    assert message.answers
    assert any("успешно подана" in ans for ans in message.answers)
    complaints = await complaint_service.list_by_order(order.order_id)
    assert len(list(complaints)) == 1


@pytest.mark.asyncio
async def test_handle_complaint_reason_other(
    fake_tm: object,
    user_repo,
    order_repo,
    order_response_repo,
    advertiser_repo,
    complaint_repo,
) -> None:
    """Handle 'Другое' reason selection."""

    advertiser = User(
        user_id=UUID("00000000-0000-0000-0000-000000000994"),
        external_id="1",
        messenger_type=MessengerType.TELEGRAM,
        username="advertiser",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    blogger = User(
        user_id=UUID("00000000-0000-0000-0000-000000000995"),
        external_id="2",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(advertiser)
    await user_repo.save(blogger)

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000000996"),
        advertiser_id=advertiser.user_id,
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        ugc_requirements=None,
        barter_description=None,
        price=1000.0,
        bloggers_needed=3,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        contacts_sent_at=None,
    )
    await order_repo.save(order)

    await order_response_repo.save(
        OrderResponse(
            response_id=UUID("00000000-0000-0000-0000-000000000997"),
            order_id=order.order_id,
            blogger_id=blogger.user_id,
            responded_at=datetime.now(timezone.utc),
        )
    )

    complaint_service = ComplaintService(complaint_repo=complaint_repo)
    order_service = build_order_service(user_repo, advertiser_repo, order_repo, fake_tm)

    from aiogram.fsm.storage.memory import MemoryStorage
    from aiogram.fsm.context import FSMContext

    storage = MemoryStorage()
    state = FSMContext(storage=storage, key="test")
    await state.update_data(
        order_id=str(order.order_id),
        reported_id=str(advertiser.user_id),
        reporter_id=str(blogger.user_id),
    )

    callback = FakeCallback(data="complaint_reason:Другое", user=FakeUser(2))
    await handle_complaint_reason(callback, state, complaint_service, order_service)

    assert callback.message.answers
    assert any("Опишите причину" in ans for ans in callback.message.answers)


@pytest.mark.asyncio
async def test_handle_complaint_reason_no_state(
    fake_tm: object, user_repo, order_repo, advertiser_repo, complaint_repo
) -> None:
    """Handle complaint reason when state is empty."""

    complaint_service = ComplaintService(complaint_repo=complaint_repo)
    order_service = OrderService(
        user_repo=user_repo,
        advertiser_repo=advertiser_repo,
        order_repo=order_repo,
    )

    from aiogram.fsm.storage.memory import MemoryStorage
    from aiogram.fsm.context import FSMContext

    storage = MemoryStorage()
    state = FSMContext(storage=storage, key="test")

    callback = FakeCallback(data="complaint_reason:Мошенничество", user=FakeUser(1))
    await handle_complaint_reason(callback, state, complaint_service, order_service)

    assert any("Сессия истекла" in ans for ans in callback.answers)


@pytest.mark.asyncio
async def test_handle_complaint_reason_invalid_reason(
    fake_tm: object, user_repo, order_repo, advertiser_repo, complaint_repo
) -> None:
    """Reject invalid reason."""

    complaint_service = ComplaintService(complaint_repo=complaint_repo)
    order_service = OrderService(
        user_repo=user_repo,
        advertiser_repo=advertiser_repo,
        order_repo=order_repo,
    )

    from aiogram.fsm.storage.memory import MemoryStorage
    from aiogram.fsm.context import FSMContext

    storage = MemoryStorage()
    state = FSMContext(storage=storage, key="test")
    await state.update_data(
        order_id=str(UUID("00000000-0000-0000-0000-000000000998")),
        reported_id=str(UUID("00000000-0000-0000-0000-000000000997")),
        reporter_id=str(UUID("00000000-0000-0000-0000-000000000996")),
    )

    callback = FakeCallback(data="complaint_reason:InvalidReason", user=FakeUser(1))
    await handle_complaint_reason(callback, state, complaint_service, order_service)

    assert any("Неверная причина" in ans for ans in callback.answers)


@pytest.mark.asyncio
async def test_handle_complaint_reason_duplicate(
    fake_tm: object,
    user_repo,
    order_repo,
    order_response_repo,
    advertiser_repo,
    complaint_repo,
) -> None:
    """Handle duplicate complaint."""

    reporter = User(
        user_id=UUID("00000000-0000-0000-0000-000000000999"),
        external_id="1",
        messenger_type=MessengerType.TELEGRAM,
        username="reporter",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(reporter)

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000001000"),
        advertiser_id=UUID("00000000-0000-0000-0000-000000001001"),
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        ugc_requirements=None,
        barter_description=None,
        price=1000.0,
        bloggers_needed=3,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        contacts_sent_at=None,
    )
    await order_repo.save(order)

    complaint_service = ComplaintService(complaint_repo=complaint_repo)
    await complaint_service.create_complaint(
        reporter_id=reporter.user_id,
        reported_id=UUID("00000000-0000-0000-0000-000000001001"),
        order_id=order.order_id,
        reason="Мошенничество",
    )

    order_service = build_order_service(user_repo, advertiser_repo, order_repo, fake_tm)

    from aiogram.fsm.storage.memory import MemoryStorage
    from aiogram.fsm.context import FSMContext

    storage = MemoryStorage()
    state = FSMContext(storage=storage, key="test")
    await state.update_data(
        order_id=str(order.order_id),
        reported_id=str(UUID("00000000-0000-0000-0000-000000001001")),
        reporter_id=str(reporter.user_id),
    )

    callback = FakeCallback(data="complaint_reason:Мошенничество", user=FakeUser(1))
    await handle_complaint_reason(callback, state, complaint_service, order_service)

    assert any("уже подали жалобу" in ans for ans in callback.answers)


@pytest.mark.asyncio
async def test_handle_complaint_reason_text_no_state(
    fake_tm: object, complaint_repo
) -> None:
    """Handle text input when state is empty."""

    complaint_service = ComplaintService(complaint_repo=complaint_repo)

    from aiogram.fsm.storage.memory import MemoryStorage
    from aiogram.fsm.context import FSMContext

    storage = MemoryStorage()
    state = FSMContext(storage=storage, key="test")

    message = FakeMessage(user=FakeUser(1))
    message.text = "Some text"

    await handle_complaint_reason_text(message, state, complaint_service)

    assert any("Сессия истекла" in ans for ans in message.answers)


@pytest.mark.asyncio
async def test_handle_complaint_reason_text_empty(
    fake_tm: object, complaint_repo
) -> None:
    """Handle empty text input."""

    complaint_service = ComplaintService(complaint_repo=complaint_repo)

    from aiogram.fsm.storage.memory import MemoryStorage
    from aiogram.fsm.context import FSMContext

    storage = MemoryStorage()
    state = FSMContext(storage=storage, key="test")
    await state.update_data(
        order_id=str(UUID("00000000-0000-0000-0000-000000001002")),
        reported_id=str(UUID("00000000-0000-0000-0000-000000001003")),
        reporter_id=str(UUID("00000000-0000-0000-0000-000000001004")),
        reason="Другое",
    )

    message = FakeMessage(user=FakeUser(1))
    message.text = "   "  # Whitespace only

    await handle_complaint_reason_text(message, state, complaint_service)

    assert any("введите причину" in ans.lower() for ans in message.answers)


@pytest.mark.asyncio
async def test_handle_complaint_reason_text_no_text(
    fake_tm: object, complaint_repo
) -> None:
    """Handle message without text."""

    complaint_service = ComplaintService(complaint_repo=complaint_repo)

    from aiogram.fsm.storage.memory import MemoryStorage
    from aiogram.fsm.context import FSMContext

    storage = MemoryStorage()
    state = FSMContext(storage=storage, key="test")

    message = FakeMessage(user=FakeUser(1))
    message.text = None

    await handle_complaint_reason_text(message, state, complaint_service)

    assert not message.answers


@pytest.mark.asyncio
async def test_start_complaint_no_data(
    fake_tm: object, user_repo, order_repo, order_response_repo, advertiser_repo
) -> None:
    """Handle callback without data."""

    user_service = UserRoleService(user_repo=user_repo)
    order_service = build_order_service(user_repo, advertiser_repo, order_repo, fake_tm)
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        response_repo=order_response_repo,
        transaction_manager=fake_tm,
    )

    from aiogram.fsm.storage.memory import MemoryStorage
    from aiogram.fsm.context import FSMContext

    storage = MemoryStorage()
    state = FSMContext(storage=storage, key="test")

    callback = FakeCallback(data="", user=FakeUser(1))
    await start_complaint(
        callback, state, user_service, order_service, offer_response_service
    )

    assert not callback.answers and not callback.message.answers


@pytest.mark.asyncio
async def test_start_complaint_user_not_found(
    fake_tm: object, user_repo, order_repo, order_response_repo, advertiser_repo
) -> None:
    """Handle complaint when user is not found."""

    user_service = UserRoleService(user_repo=user_repo)
    order_service = build_order_service(user_repo, advertiser_repo, order_repo, fake_tm)
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        response_repo=order_response_repo,
        transaction_manager=fake_tm,
    )

    from aiogram.fsm.storage.memory import MemoryStorage
    from aiogram.fsm.context import FSMContext

    storage = MemoryStorage()
    state = FSMContext(storage=storage, key="test")

    callback = FakeCallback(
        data=f"complaint:{UUID('00000000-0000-0000-0000-000000001010')}:{UUID('00000000-0000-0000-0000-000000001011')}",
        user=FakeUser(999),
    )
    await start_complaint(
        callback, state, user_service, order_service, offer_response_service
    )

    assert any("Пользователь не найден" in ans for ans in callback.answers)


@pytest.mark.asyncio
async def test_start_complaint_invalid_reported_id(
    fake_tm: object, user_repo, order_repo, order_response_repo, advertiser_repo
) -> None:
    """Reject complaint with invalid reported_id."""

    advertiser = User(
        user_id=UUID("00000000-0000-0000-0000-000000001020"),
        external_id="1",
        messenger_type=MessengerType.TELEGRAM,
        username="advertiser",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    blogger = User(
        user_id=UUID("00000000-0000-0000-0000-000000001021"),
        external_id="2",
        messenger_type=MessengerType.TELEGRAM,
        username="blogger",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(advertiser)
    await user_repo.save(blogger)

    order = Order(
        order_id=UUID("00000000-0000-0000-0000-000000001022"),
        advertiser_id=advertiser.user_id,
        order_type=OrderType.UGC_ONLY,
        product_link="https://example.com",
        offer_text="Offer",
        ugc_requirements=None,
        barter_description=None,
        price=1000.0,
        bloggers_needed=3,
        status=OrderStatus.ACTIVE,
        created_at=datetime.now(timezone.utc),
        contacts_sent_at=None,
    )
    await order_repo.save(order)

    await order_response_repo.save(
        OrderResponse(
            response_id=UUID("00000000-0000-0000-0000-000000001023"),
            order_id=order.order_id,
            blogger_id=blogger.user_id,
            responded_at=datetime.now(timezone.utc),
        )
    )

    user_service = UserRoleService(user_repo=user_repo)
    order_service = build_order_service(user_repo, advertiser_repo, order_repo, fake_tm)
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        response_repo=order_response_repo,
        transaction_manager=fake_tm,
    )

    from aiogram.fsm.storage.memory import MemoryStorage
    from aiogram.fsm.context import FSMContext

    storage = MemoryStorage()
    state = FSMContext(storage=storage, key="test")

    # Invalid reported_id (not a blogger who responded)
    callback = FakeCallback(
        data=f"complaint:{order.order_id}:{UUID('00000000-0000-0000-0000-000000001099')}",
        user=FakeUser(1),
    )
    await start_complaint(
        callback, state, user_service, order_service, offer_response_service
    )

    assert any("Неверный идентификатор пользователя" in ans for ans in callback.answers)


@pytest.mark.asyncio
async def test_select_complaint_target_no_from_user(
    fake_tm: object,
    user_repo,
    order_repo,
    order_response_repo,
    advertiser_repo,
    complaint_repo,
) -> None:
    """Handle callback without from_user."""

    user_service = UserRoleService(user_repo=user_repo)
    order_service = build_order_service(user_repo, advertiser_repo, order_repo, fake_tm)
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        response_repo=order_response_repo,
        transaction_manager=fake_tm,
    )

    from aiogram.fsm.storage.memory import MemoryStorage
    from aiogram.fsm.context import FSMContext

    storage = MemoryStorage()
    state = FSMContext(storage=storage, key="test")

    callback = FakeCallback(data="complaint_select:123", user=FakeUser(1))
    callback.from_user = None

    await select_complaint_target(
        callback,
        state,
        user_service,
        order_service,
        offer_response_service,
        None,
    )

    assert not callback.answers and not callback.message.answers


@pytest.mark.asyncio
async def test_select_complaint_target_invalid_uuid(
    fake_tm: object,
    user_repo,
    order_repo,
    order_response_repo,
    advertiser_repo,
    complaint_repo,
) -> None:
    """Reject invalid UUID format."""

    user = User(
        user_id=UUID("00000000-0000-0000-0000-000000001010"),
        external_id="1",
        messenger_type=MessengerType.TELEGRAM,
        username="user",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
    )
    await user_repo.save(user)

    user_service = UserRoleService(user_repo=user_repo)
    order_service = build_order_service(user_repo, advertiser_repo, order_repo, fake_tm)
    offer_response_service = OfferResponseService(
        order_repo=order_repo,
        response_repo=order_response_repo,
        transaction_manager=fake_tm,
    )

    from aiogram.fsm.storage.memory import MemoryStorage
    from aiogram.fsm.context import FSMContext

    storage = MemoryStorage()
    state = FSMContext(storage=storage, key="test")

    callback = FakeCallback(data="complaint_select:not-a-uuid", user=FakeUser(1))
    await select_complaint_target(
        callback,
        state,
        user_service,
        order_service,
        offer_response_service,
        None,
    )

    assert any("Неверный формат идентификатора" in ans for ans in callback.answers)
