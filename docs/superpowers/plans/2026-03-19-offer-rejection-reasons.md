# Offer Rejection Reasons — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Capture rejection reasons when creators skip offers, with special handling for "low price" (desired price input + manager notification).

**Architecture:** Extend the existing `OfferDispatch` entity with `rejection_reason` (StrEnum) and `desired_price` (Decimal). Add FSM state for price input. Handler shows reason menu on skip, records reason, notifies manager on LOW_PRICE. Service returns `SkipResult` dataclass.

**Tech Stack:** Python 3.12, aiogram 3, SQLAlchemy 2, Alembic, PostgreSQL, pytest

**Spec:** `docs/superpowers/specs/2026-03-19-offer-rejection-reasons-design.md`

---

### Task 1: Domain — Add `RejectionReason` enum

**Files:**
- Modify: `src/ugc_bot/domain/enums.py` (add enum at end)
- Modify: `src/ugc_bot/domain/entities.py:220-240` (add fields to `OfferDispatch`)

- [ ] **Step 1: Add `RejectionReason` enum to `domain/enums.py`**

At the end of the file, add:

```python
class RejectionReason(StrEnum):
    LOW_PRICE = "low_price"
    WRONG_FORMAT = "wrong_format"
    UNINTERESTING_PRODUCT = "uninteresting_product"
    NO_TIME = "no_time"
```

- [ ] **Step 2: Add fields to `OfferDispatch` entity in `domain/entities.py`**

Import `Decimal` from `decimal` and `RejectionReason` from `domain.enums`. Add two fields after `ugc_video_url` in the `OfferDispatch` dataclass:

```python
rejection_reason: Optional[RejectionReason] = None
desired_price: Optional[Decimal] = None
```

- [ ] **Step 3: Commit**

```bash
git add src/ugc_bot/domain/enums.py src/ugc_bot/domain/entities.py
git commit -m "feat: add RejectionReason enum and OfferDispatch fields"
```

---

### Task 2: Database — Migration and model

**Files:**
- Create: `src/ugc_bot/infrastructure/db/migrations/versions/0078_add_rejection_reason_to_offer_dispatches.py`
- Modify: `src/ugc_bot/infrastructure/db/models.py:455-487` (add columns to `OfferDispatchModel`)

- [ ] **Step 1: Create Alembic migration**

Create `src/ugc_bot/infrastructure/db/migrations/versions/0078_add_rejection_reason_to_offer_dispatches.py`:

```python
"""Add rejection_reason and desired_price to offer_dispatches."""

import sqlalchemy as sa
from alembic import op

revision = "0078_add_rejection_reason_to_offer_dispatches"
down_revision = "0077_add_phone_to_blogger_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add nullable rejection_reason and desired_price columns."""
    op.add_column(
        "offer_dispatches",
        sa.Column("rejection_reason", sa.String(), nullable=True),
    )
    op.add_column(
        "offer_dispatches",
        sa.Column("desired_price", sa.Numeric(), nullable=True),
    )


def downgrade() -> None:
    """Remove rejection_reason and desired_price columns."""
    op.drop_column("offer_dispatches", "desired_price")
    op.drop_column("offer_dispatches", "rejection_reason")
```

- [ ] **Step 2: Add columns to `OfferDispatchModel`**

In `src/ugc_bot/infrastructure/db/models.py`, add to the `OfferDispatchModel` class after `ugc_video_url`:

```python
rejection_reason: Mapped[Optional[str]] = mapped_column(
    sa.String, nullable=True, default=None
)
desired_price: Mapped[Optional[sa.Numeric]] = mapped_column(
    sa.Numeric, nullable=True, default=None
)
```

Use the same `Mapped[Optional[...]]` pattern as `ugc_video_url`.

- [ ] **Step 3: Commit**

```bash
git add src/ugc_bot/infrastructure/db/migrations/versions/0078_add_rejection_reason_to_offer_dispatches.py src/ugc_bot/infrastructure/db/models.py
git commit -m "feat: add rejection_reason and desired_price to offer_dispatches table"
```

---

### Task 3: Repository layer — Extend `record_response`

**Files:**
- Modify: `src/ugc_bot/application/ports.py:252-274` (add params to `record_response` abstract method)
- Modify: `src/ugc_bot/infrastructure/db/repositories/interactions.py:49-75` (add params to SQL impl)
- Modify: `src/ugc_bot/infrastructure/memory_repositories.py:723-743` (add params to in-memory impl)

- [ ] **Step 1: Update abstract `record_response` in `ports.py`**

Add two new parameters after `manager_id`:

```python
async def record_response(
    self,
    order_id: UUID,
    blogger_id: UUID,
    accepted: bool,
    in_offer: bool,
    session: object | None = None,
    manager_id: UUID | None = None,
    rejection_reason: str | None = None,
    desired_price: object | None = None,  # Decimal
) -> None:
```

- [ ] **Step 2: Update `SqlAlchemyOfferDispatchRepository.record_response` in `interactions.py`**

Add `rejection_reason` and `desired_price` params. Pass them to `.values(...)`:

```python
async def record_response(
    self,
    order_id: UUID,
    blogger_id: UUID,
    accepted: bool,
    in_offer: bool,
    session: object | None = None,
    manager_id: UUID | None = None,
    rejection_reason: str | None = None,
    desired_price: object | None = None,
) -> None:
    """Update dispatch with response (accepted/in_offer) and updated_at."""
    async with _resolve_session(
        self.session_factory, session
    ) as db_session:
        now = datetime.now(timezone.utc)
        await db_session.execute(
            update(OfferDispatchModel)
            .where(
                OfferDispatchModel.order_id == order_id,
                OfferDispatchModel.blogger_id == blogger_id,
            )
            .values(
                accepted=accepted,
                in_offer=in_offer,
                updated_at=now,
                manager_id=manager_id,
                rejection_reason=rejection_reason,
                desired_price=desired_price,
            )
        )
```

- [ ] **Step 3: Update `InMemoryOfferDispatchRepository.record_response` in `memory_repositories.py`**

Add `rejection_reason` and `desired_price` params. Pass them to `replace(...)`:

```python
async def record_response(
    self,
    order_id: UUID,
    blogger_id: UUID,
    accepted: bool,
    in_offer: bool,
    session: object | None = None,
    manager_id: UUID | None = None,
    rejection_reason: str | None = None,
    desired_price: object | None = None,
) -> None:
    """Update dispatch with response (accepted/in_offer) and updated_at."""
    key = (order_id, blogger_id)
    now = datetime.now(timezone.utc)
    if key in self._dispatches:
        d = self._dispatches[key]
        self._dispatches[key] = replace(
            d,
            updated_at=now,
            accepted=accepted,
            in_offer=in_offer,
            manager_id=manager_id,
            rejection_reason=rejection_reason,
            desired_price=desired_price,
        )
```

Note: `rejection_reason` is stored as `str` (the enum `.value`), since that's what `RejectionReason(StrEnum)` produces.

- [ ] **Step 4: Update entity mapper in `interactions.py`**

Find the `_to_offer_dispatch_entity` function (or equivalent mapper) and add `rejection_reason` and `desired_price` to the mapping. Map `rejection_reason` string back to `RejectionReason` enum (or `None`).

- [ ] **Step 5: Run existing tests to verify nothing breaks**

```bash
uv run pytest tests/bot/handlers/test_offer_responses.py tests/application/services/test_offer_dispatch_service.py -v
```

Expected: all existing tests PASS (new params have defaults).

- [ ] **Step 6: Commit**

```bash
git add src/ugc_bot/application/ports.py src/ugc_bot/infrastructure/db/repositories/interactions.py src/ugc_bot/infrastructure/memory_repositories.py
git commit -m "feat: extend record_response with rejection_reason and desired_price"
```

---

### Task 4: Service layer — Extend `record_skip` and add `SkipResult`

**Files:**
- Modify: `src/ugc_bot/application/services/offer_dispatch_service.py:559-576` (extend `record_skip`)
- Test: `tests/application/services/test_offer_dispatch_service.py`

- [ ] **Step 1: Write failing test for `record_skip` with rejection reason**

Add to `tests/application/services/test_offer_dispatch_service.py`:

```python
from decimal import Decimal
from ugc_bot.application.services.offer_dispatch_service import SkipResult
from ugc_bot.domain.enums import RejectionReason


@pytest.mark.asyncio
async def test_record_skip_with_rejection_reason():
    """record_skip stores rejection_reason and returns SkipResult."""
    offer_dispatch_repo = InMemoryOfferDispatchRepository()
    order_repo = InMemoryOrderRepository()
    order = await create_test_order(
        order_repo,
        advertiser_id=UUID("00000000-0000-0000-0000-000000000001"),
        order_id=UUID("00000000-0000-0000-0000-000000000002"),
    )
    blogger_id = UUID("00000000-0000-0000-0000-000000000003")
    await offer_dispatch_repo.record_sent(order.order_id, blogger_id)
    service = OfferDispatchService(
        user_repo=InMemoryUserRepository(),
        blogger_repo=InMemoryBloggerProfileRepository(),
        order_repo=order_repo,
        offer_dispatch_repo=offer_dispatch_repo,
        interaction_repo=InMemoryInteractionRepository(),
    )
    result = await service.record_skip(
        order.order_id,
        blogger_id,
        rejection_reason=RejectionReason.WRONG_FORMAT,
    )
    assert isinstance(result, SkipResult)
    assert result.rejection_reason == RejectionReason.WRONG_FORMAT
    assert result.desired_price is None
    dispatch = offer_dispatch_repo._dispatches[(order.order_id, blogger_id)]
    assert dispatch.accepted is False
    assert dispatch.rejection_reason == RejectionReason.WRONG_FORMAT


@pytest.mark.asyncio
async def test_record_skip_low_price_returns_manager_id():
    """record_skip with LOW_PRICE returns manager_id in SkipResult."""
    offer_dispatch_repo = InMemoryOfferDispatchRepository()
    order_repo = InMemoryOrderRepository()
    manager_order_repo = InMemoryManagerOrderRepository()
    manager_id = UUID("00000000-0000-0000-0000-000000000010")
    order = await create_test_order(
        order_repo,
        advertiser_id=UUID("00000000-0000-0000-0000-000000000001"),
        order_id=UUID("00000000-0000-0000-0000-000000000002"),
        price=1000.0,
    )
    # Assign manager to order
    await manager_order_repo.save(ManagerOrder(
        order_id=order.order_id, user_id=manager_id,
    ))
    blogger_id = UUID("00000000-0000-0000-0000-000000000003")
    await offer_dispatch_repo.record_sent(order.order_id, blogger_id)
    service = OfferDispatchService(
        user_repo=InMemoryUserRepository(),
        blogger_repo=InMemoryBloggerProfileRepository(),
        order_repo=order_repo,
        offer_dispatch_repo=offer_dispatch_repo,
        interaction_repo=InMemoryInteractionRepository(),
        manager_order_repo=manager_order_repo,
    )
    result = await service.record_skip(
        order.order_id,
        blogger_id,
        rejection_reason=RejectionReason.LOW_PRICE,
        desired_price=Decimal("5000"),
    )
    assert result.rejection_reason == RejectionReason.LOW_PRICE
    assert result.desired_price == Decimal("5000")
    assert result.manager_id == manager_id
    assert result.order_price is not None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/application/services/test_offer_dispatch_service.py::test_record_skip_with_rejection_reason tests/application/services/test_offer_dispatch_service.py::test_record_skip_low_price_returns_manager_id -v
```

Expected: FAIL (SkipResult doesn't exist yet).

- [ ] **Step 3: Implement `SkipResult` and extend `record_skip`**

In `src/ugc_bot/application/services/offer_dispatch_service.py`:

1. Add imports:
```python
from decimal import Decimal
from ugc_bot.application.ports import ManagerOrderRepository
from ugc_bot.domain.enums import RejectionReason
```

2. Add `SkipResult` dataclass after `_DispatchCriteria`:
```python
@dataclass(slots=True)
class SkipResult:
    """Result of recording a skip with rejection reason."""
    rejection_reason: RejectionReason | None = None
    desired_price: Decimal | None = None
    manager_id: UUID | None = None
    order_price: Decimal | None = None
```

3. Add `manager_order_repo` field to `OfferDispatchService` (optional, after `country_repo`):
```python
manager_order_repo: ManagerOrderRepository | None = None
```

4. Replace `record_skip` method:
```python
async def record_skip(
    self,
    order_id: UUID,
    blogger_id: UUID,
    rejection_reason: RejectionReason | None = None,
    desired_price: Decimal | None = None,
    session: object | None = None,
) -> SkipResult:
    """Record blogger skip with optional rejection reason."""

    async def _run(sess: object | None) -> SkipResult:
        await self.offer_dispatch_repo.record_response(
            order_id,
            blogger_id,
            accepted=False,
            in_offer=False,
            session=sess,
            rejection_reason=rejection_reason.value if rejection_reason else None,
            desired_price=desired_price,
        )
        manager_id: UUID | None = None
        order_price: Decimal | None = None
        if rejection_reason == RejectionReason.LOW_PRICE and self.manager_order_repo:
            assignments = await self.manager_order_repo.list_by_order(
                order_id, session=sess
            )
            if assignments:
                manager_id = assignments[0].user_id
            order = await self.order_repo.get_by_id(order_id, session=sess)
            if order:
                order_price = Decimal(str(order.price))
        return SkipResult(
            rejection_reason=rejection_reason,
            desired_price=desired_price,
            manager_id=manager_id,
            order_price=order_price,
        )

    return await with_optional_tx(self.transaction_manager, _run)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/application/services/test_offer_dispatch_service.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/ugc_bot/application/services/offer_dispatch_service.py tests/application/services/test_offer_dispatch_service.py
git commit -m "feat: add SkipResult and extend record_skip with rejection reason"
```

---

### Task 5: Update container wiring

**Files:**
- Modify: `src/ugc_bot/container/service_factory.py:124-138` (add `manager_order_repo` to `build_offer_dispatch_service`)
- Modify: `src/ugc_bot/container/service_factory.py:405-414` (add `manager_order_repo` to bot service wiring)

- [ ] **Step 1: Add `manager_order_repo` to both `OfferDispatchService` constructions**

In `build_offer_dispatch_service` (line 128), add:
```python
manager_order_repo=repos.get("manager_order_repo"),
```

In the bot services dict (line 405), add:
```python
manager_order_repo=repos.get("manager_order_repo"),
```

- [ ] **Step 2: Commit**

```bash
git add src/ugc_bot/container/service_factory.py
git commit -m "feat: wire manager_order_repo into OfferDispatchService"
```

---

### Task 6: Localization — Add text keys

**Files:**
- Modify: `src/ugc_bot/bot/texts/defaults/ru.py`
- Modify: `src/ugc_bot/bot/texts/defaults/en.py`
- Modify: `src/ugc_bot/bot/texts/defaults/be.py`
- Modify: `src/ugc_bot/bot/texts/defaults/kk.py`
- Modify: `src/ugc_bot/bot/texts/defaults/uz.py`

- [ ] **Step 1: Add Russian text keys to `ru.py`**

Add to the `DEFAULT_TEXTS["ru"]` dict:

```python
"msg_offer_skip_reason_prompt": "Укажите причину отказа:",
"btn_reject_low_price": "Низкая цена",
"btn_reject_wrong_format": "Не подходит формат рекламы",
"btn_reject_uninteresting": "Неинтересный продукт / предложение",
"btn_reject_no_time": "Нет времени",
"msg_enter_desired_price": "Укажите, за какую стоимость вы готовы разместить рекламу:",
"msg_invalid_price": "Введите число от {min} до {max} {currency}",
"msg_offer_skipped_with_reason": "Спасибо за обратную связь. Вы отказались: {reason}. Пропущено.",
"msg_offer_skipped_low_price": "Спасибо за обратную связь. Вы отказались: Низкая цена. Желаемая сумма: {price} {currency}. Мы можем вернуться с новым предложением.",
"msg_manager_low_price_notification": "Блогер {blogger} отказался от заказа «{order}»: низкая цена. Готов за {desired_price} {currency} (в оффере: {offer_price} {currency}).",
"btn_cancel_price_entry": "Отмена",
"msg_price_entry_cancelled": "Отказ записан. Пропущено.",
```

- [ ] **Step 2: Add English text keys to `en.py`**

```python
"msg_offer_skip_reason_prompt": "Please select a reason:",
"btn_reject_low_price": "Low price",
"btn_reject_wrong_format": "Wrong ad format",
"btn_reject_uninteresting": "Uninteresting product",
"btn_reject_no_time": "No time",
"msg_enter_desired_price": "Enter your desired price:",
"msg_invalid_price": "Enter a number from {min} to {max} {currency}",
"msg_offer_skipped_with_reason": "Thanks for feedback. Declined: {reason}. Skipped.",
"msg_offer_skipped_low_price": "Thanks. Declined: Low price. Desired: {price} {currency}. We may return with a new offer.",
"msg_manager_low_price_notification": "Blogger {blogger} declined \"{order}\": low price. Wants {desired_price} {currency} (offered: {offer_price} {currency}).",
"btn_cancel_price_entry": "Cancel",
"msg_price_entry_cancelled": "Decline recorded. Skipped.",
```

- [ ] **Step 3: Add Belarusian text keys to `be.py`**

```python
"msg_offer_skip_reason_prompt": "Пазначце прычыну адмовы:",
"btn_reject_low_price": "Нізкая цана",
"btn_reject_wrong_format": "Не падыходзіць фармат рэкламы",
"btn_reject_uninteresting": "Нецікавы прадукт / прапанова",
"btn_reject_no_time": "Няма часу",
"msg_enter_desired_price": "Пазначце, за які кошт вы гатовы размясціць рэкламу:",
"msg_invalid_price": "Увядзіце лік ад {min} да {max} {currency}",
"msg_offer_skipped_with_reason": "Дзякуй за зваротную сувязь. Вы адмовіліся: {reason}. Прапушчана.",
"msg_offer_skipped_low_price": "Дзякуй. Адмовіліся: Нізкая цана. Жаданая сума: {price} {currency}. Мы можам вярнуцца з новай прапановай.",
"msg_manager_low_price_notification": "Блогер {blogger} адмовіўся ад замовы «{order}»: нізкая цана. Гатовы за {desired_price} {currency} (у оферы: {offer_price} {currency}).",
"btn_cancel_price_entry": "Адмена",
"msg_price_entry_cancelled": "Адмова запісана. Прапушчана.",
```

- [ ] **Step 4: Add Kazakh text keys to `kk.py`**

```python
"msg_offer_skip_reason_prompt": "Бас тарту себебін көрсетіңіз:",
"btn_reject_low_price": "Баға төмен",
"btn_reject_wrong_format": "Жарнама форматы сәйкес келмейді",
"btn_reject_uninteresting": "Қызықсыз өнім / ұсыныс",
"btn_reject_no_time": "Уақыт жоқ",
"msg_enter_desired_price": "Жарнаманы қанша бағаға орналастыруға дайынсыз:",
"msg_invalid_price": "{min} мен {max} {currency} арасында сан енгізіңіз",
"msg_offer_skipped_with_reason": "Кері байланыс үшін рахмет. Бас тарттыңыз: {reason}. Өткізілді.",
"msg_offer_skipped_low_price": "Рахмет. Бас тарту: Баға төмен. Қалаған сома: {price} {currency}. Жаңа ұсыныспен қайта ораламыз.",
"msg_manager_low_price_notification": "Блогер {blogger} «{order}» тапсырысынан бас тартты: баға төмен. {desired_price} {currency} дайын (офферде: {offer_price} {currency}).",
"btn_cancel_price_entry": "Болдырмау",
"msg_price_entry_cancelled": "Бас тарту жазылды. Өткізілді.",
```

- [ ] **Step 5: Add Uzbek text keys to `uz.py`**

```python
"msg_offer_skip_reason_prompt": "Rad etish sababini ko'rsating:",
"btn_reject_low_price": "Narx past",
"btn_reject_wrong_format": "Reklama formati mos emas",
"btn_reject_uninteresting": "Qiziq bo'lmagan mahsulot / taklif",
"btn_reject_no_time": "Vaqt yo'q",
"msg_enter_desired_price": "Qancha narxga reklama joylashga tayyorsiz:",
"msg_invalid_price": "{min} dan {max} {currency} gacha son kiriting",
"msg_offer_skipped_with_reason": "Fikr-mulohaza uchun rahmat. Rad ettingiz: {reason}. O'tkazib yuborildi.",
"msg_offer_skipped_low_price": "Rahmat. Rad: Narx past. Xohlagan summa: {price} {currency}. Yangi taklif bilan qaytishimiz mumkin.",
"msg_manager_low_price_notification": "Bloger {blogger} «{order}» buyurtmasidan voz kechdi: narx past. {desired_price} {currency} tayyor (offerda: {offer_price} {currency}).",
"btn_cancel_price_entry": "Bekor qilish",
"msg_price_entry_cancelled": "Rad etish yozildi. O'tkazib yuborildi.",
```

- [ ] **Step 6: Commit**

```bash
git add src/ugc_bot/bot/texts/defaults/
git commit -m "feat: add rejection reason text keys for all 5 locales"
```

---

### Task 7: Bot handler — Rejection reason selection + FSM for price

**Files:**
- Modify: `src/ugc_bot/bot/handlers/offer_responses.py`
- Test: `tests/bot/handlers/test_offer_responses.py`

This is the main handler task. It modifies `handle_offer_skip` and adds new handlers.

- [ ] **Step 1: Write failing tests**

Add to `tests/bot/handlers/test_offer_responses.py`:

```python
from ugc_bot.bot.handlers.offer_responses import (
    handle_offer_skip,
    handle_rejection_reason,
    handle_desired_price,
    handle_cancel_price_entry,
    OfferSkipStates,
)
from ugc_bot.domain.enums import RejectionReason


@pytest.mark.asyncio
async def test_offer_skip_shows_reason_menu(
    user_repo, config, bot_texts_service, messenger_client, event_adapter,
):
    """Pressing 'Пропустить' now shows reason selection menu."""
    blogger_user = await create_test_user(user_repo, external_id="1")
    offer_dispatch_repo = InMemoryOfferDispatchRepository()
    service = OfferDispatchService(
        user_repo=user_repo,
        blogger_repo=InMemoryBloggerProfileRepository(),
        order_repo=InMemoryOrderRepository(),
        offer_dispatch_repo=offer_dispatch_repo,
        interaction_repo=InMemoryInteractionRepository(),
    )
    order_id = UUID("00000000-0000-0000-0000-000000000748")
    await offer_dispatch_repo.record_sent(order_id, blogger_user.user_id)
    message = FakeMessage()
    callback = FakeCallback(
        data=f"offer_skip:{order_id}",
        user=FakeUser(1),
        message=message,
    )
    await handle_offer_skip(
        callback,
        user_role_service=UserRoleService(user_repo=user_repo),
        offer_dispatch_service=service,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )
    # Should show reason menu (send_text with inline keyboard)
    assert messenger_client.sent_texts  # reason prompt was sent
    # Original keyboard should be removed
    assert len(message.edit_reply_markup_calls) == 1


@pytest.mark.asyncio
async def test_rejection_reason_non_price_records_skip(
    user_repo, config, bot_texts_service, messenger_client, event_adapter,
):
    """Selecting a non-price reason records skip immediately."""
    blogger_user = await create_test_user(user_repo, external_id="1")
    offer_dispatch_repo = InMemoryOfferDispatchRepository()
    order_repo = InMemoryOrderRepository()
    order = await create_test_order(
        order_repo,
        blogger_user.user_id,
        order_id=UUID("00000000-0000-0000-0000-000000000748"),
    )
    await offer_dispatch_repo.record_sent(order.order_id, blogger_user.user_id)
    service = OfferDispatchService(
        user_repo=user_repo,
        blogger_repo=InMemoryBloggerProfileRepository(),
        order_repo=order_repo,
        offer_dispatch_repo=offer_dispatch_repo,
        interaction_repo=InMemoryInteractionRepository(),
    )
    order_hex = order.order_id.hex
    callback = FakeCallback(
        data=f"orr:{order_hex}:wrong_format",
        user=FakeUser(1),
        message=FakeMessage(),
    )
    await handle_rejection_reason(
        callback,
        user_role_service=UserRoleService(user_repo=user_repo),
        offer_dispatch_service=service,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )
    dispatch = offer_dispatch_repo._dispatches[(order.order_id, blogger_user.user_id)]
    assert dispatch.accepted is False
    assert dispatch.rejection_reason == "wrong_format"


@pytest.mark.asyncio
async def test_rejection_reason_low_price_enters_fsm(
    user_repo, config, bot_texts_service, messenger_client, event_adapter,
):
    """Selecting LOW_PRICE enters FSM state for price entry."""
    blogger_user = await create_test_user(user_repo, external_id="1")
    offer_dispatch_repo = InMemoryOfferDispatchRepository()
    order_repo = InMemoryOrderRepository()
    order = await create_test_order(
        order_repo,
        blogger_user.user_id,
        order_id=UUID("00000000-0000-0000-0000-000000000748"),
        price=1000.0,
    )
    await offer_dispatch_repo.record_sent(order.order_id, blogger_user.user_id)
    service = OfferDispatchService(
        user_repo=user_repo,
        blogger_repo=InMemoryBloggerProfileRepository(),
        order_repo=order_repo,
        offer_dispatch_repo=offer_dispatch_repo,
        interaction_repo=InMemoryInteractionRepository(),
    )
    state = FakeFSMContext()
    order_hex = order.order_id.hex
    callback = FakeCallback(
        data=f"orr:{order_hex}:low_price",
        user=FakeUser(1),
        message=FakeMessage(),
    )
    await handle_rejection_reason(
        callback,
        state=state,
        user_role_service=UserRoleService(user_repo=user_repo),
        offer_dispatch_service=service,
        config=config,
        bot_texts_service=bot_texts_service,
        messenger_client=messenger_client,
        event_adapter=event_adapter,
    )
    # Should enter FSM waiting_desired_price
    assert state.current_state == OfferSkipStates.waiting_desired_price
    state_data = await state.get_data()
    assert str(order.order_id) in str(state_data.get("order_id", ""))
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/bot/handlers/test_offer_responses.py::test_offer_skip_shows_reason_menu tests/bot/handlers/test_offer_responses.py::test_rejection_reason_non_price_records_skip tests/bot/handlers/test_offer_responses.py::test_rejection_reason_low_price_enters_fsm -v
```

Expected: FAIL (new handlers don't exist yet).

- [ ] **Step 3: Add FSM states and reason-to-button mapping**

At the top of `offer_responses.py`, add imports and FSM class:

```python
from decimal import Decimal, InvalidOperation
from aiogram.fsm.state import State, StatesGroup
from ugc_bot.domain.enums import RejectionReason

class OfferSkipStates(StatesGroup):
    waiting_desired_price = State()

_REJECTION_REASON_BUTTONS = {
    RejectionReason.LOW_PRICE: "btn_reject_low_price",
    RejectionReason.WRONG_FORMAT: "btn_reject_wrong_format",
    RejectionReason.UNINTERESTING_PRODUCT: "btn_reject_uninteresting",
    RejectionReason.NO_TIME: "btn_reject_no_time",
}

_REASON_DISPLAY_KEYS = {
    RejectionReason.LOW_PRICE: "btn_reject_low_price",
    RejectionReason.WRONG_FORMAT: "btn_reject_wrong_format",
    RejectionReason.UNINTERESTING_PRODUCT: "btn_reject_uninteresting",
    RejectionReason.NO_TIME: "btn_reject_no_time",
}
```

- [ ] **Step 4: Rewrite `handle_offer_skip` to show reason menu**

Replace the existing `handle_offer_skip` body to:
1. Answer callback (empty toast)
2. Remove original offer keyboard
3. Send new message with reason selection inline keyboard

Each button: `orr:{order_id_hex}:{reason_value}`

```python
@router.callback_query(
    lambda callback: callback.data and callback.data.startswith("offer_skip:")
)
async def handle_offer_skip(
    callback: CallbackQuery,
    user_role_service: UserRoleService,
    offer_dispatch_service: OfferDispatchService,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Show rejection reason menu when blogger presses 'Пропустить'."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    locale = user_locale
    order_id = _parse_offer_skip_order_id(callback.data or "")
    user = await get_user_and_ensure_allowed_callback(
        incoming, messenger_client, user_role_service,
        user_not_found_msg=await bot_texts_service.get("msg_offer_skipped", locale),
        blocked_msg=await bot_texts_service.get("msg_offer_skipped", locale),
        pause_msg=await bot_texts_service.get("msg_offer_skipped", locale),
    )
    await messenger_client.answer_callback(callback_id=incoming.callback_id, text="")
    if incoming.message_id:
        with contextlib.suppress(Exception):
            await messenger_client.edit_reply_markup(
                chat_id=incoming.chat_id, message_id=incoming.message_id, keyboard=None,
            )
    if user is None or order_id is None:
        return
    user = await user_role_service.update_telegram(user, callback.from_user.username)

    # Build reason selection keyboard
    text_keys = ["msg_offer_skip_reason_prompt"] + list(_REJECTION_REASON_BUTTONS.values())
    texts = await bot_texts_service.get_many(text_keys, locale)
    prompt = texts.get("msg_offer_skip_reason_prompt", "Укажите причину отказа:")
    order_hex = order_id.hex
    rows = []
    for reason, text_key in _REJECTION_REASON_BUTTONS.items():
        btn_text = texts.get(text_key, reason.value)
        rows.append([Button(text=btn_text, callback_data=f"orr:{order_hex}:{reason.value}")])
    keyboard = Keyboard(kind=KeyboardKind.INLINE, rows=rows)
    await messenger_client.send_text(chat_id=incoming.chat_id, text=prompt, keyboard=keyboard)
```

- [ ] **Step 5: Add `handle_rejection_reason` handler**

```python
def _parse_orr_callback(data: str) -> tuple[UUID | None, str | None]:
    """Parse 'orr:{order_hex}:{reason}' callback data."""
    if not data or not data.startswith("orr:"):
        return None, None
    parts = data.split(":", 2)
    if len(parts) != 3:
        return None, None
    try:
        order_id = UUID(parts[1])
    except ValueError:
        return None, None
    return order_id, parts[2]


@router.callback_query(
    lambda callback: callback.data and callback.data.startswith("orr:") and not callback.data.startswith("orr_cancel:")
)
async def handle_rejection_reason(
    callback: CallbackQuery,
    user_role_service: UserRoleService,
    offer_dispatch_service: OfferDispatchService,
    config: AppConfig,
    bot_texts_service: BotTextsService,
    user_locale: str = "ru",
    state: FSMContext | None = None,
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle rejection reason selection."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    locale = user_locale
    order_id, reason_str = _parse_orr_callback(callback.data or "")
    user = await get_user_and_ensure_allowed_callback(
        incoming, messenger_client, user_role_service,
        user_not_found_msg="", blocked_msg="", pause_msg="",
    )
    if user is None or order_id is None or reason_str is None:
        await messenger_client.answer_callback(callback_id=incoming.callback_id, text="")
        return
    user = await user_role_service.update_telegram(user, callback.from_user.username)

    try:
        reason = RejectionReason(reason_str)
    except ValueError:
        await messenger_client.answer_callback(callback_id=incoming.callback_id, text="")
        return

    # Remove reason menu keyboard
    if incoming.message_id:
        with contextlib.suppress(Exception):
            await messenger_client.edit_reply_markup(
                chat_id=incoming.chat_id, message_id=incoming.message_id, keyboard=None,
            )

    if reason == RejectionReason.LOW_PRICE:
        # Enter FSM for price entry
        if state is not None:
            await state.set_state(OfferSkipStates.waiting_desired_price)
            await state.update_data(order_id=str(order_id), reason=reason_str)
        prompt = await bot_texts_service.get("msg_enter_desired_price", locale)
        order_hex = order_id.hex
        cancel_text = await bot_texts_service.get("btn_cancel_price_entry", locale)
        cancel_kb = Keyboard(kind=KeyboardKind.INLINE, rows=[
            [Button(text=cancel_text, callback_data=f"orr_cancel:{order_hex}")]
        ])
        await messenger_client.send_text(
            chat_id=incoming.chat_id, text=prompt, keyboard=cancel_kb,
        )
        await messenger_client.answer_callback(callback_id=incoming.callback_id, text="")
        return

    # Non-price reasons: record skip immediately
    result = await offer_dispatch_service.record_skip(
        order_id, user.user_id, rejection_reason=reason,
    )
    reason_display = await bot_texts_service.get(
        _REASON_DISPLAY_KEYS.get(reason, ""), locale
    ) or reason.value
    msg = await bot_texts_service.get("msg_offer_skipped_with_reason", locale)
    confirmation = msg.format(reason=reason_display) if msg else f"Пропущено: {reason_display}"
    await messenger_client.answer_callback(callback_id=incoming.callback_id, text="")
    await messenger_client.send_text(chat_id=incoming.chat_id, text=confirmation)
```

- [ ] **Step 6: Add `handle_desired_price` FSM handler**

```python
@router.message(OfferSkipStates.waiting_desired_price)
async def handle_desired_price(
    message: Message,
    state: FSMContext,
    user_role_service: UserRoleService,
    offer_dispatch_service: OfferDispatchService,
    bot_texts_service: BotTextsService,
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Handle price input during LOW_PRICE rejection flow."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        message, messenger_client, event_adapter
    )
    locale = user_locale
    data = await state.get_data()
    order_id_str = data.get("order_id")

    if not message.text or not order_id_str:
        prompt = await bot_texts_service.get("msg_enter_desired_price", locale)
        await messenger_client.send_text(chat_id=str(message.chat.id), text=prompt)
        return

    order_id = UUID(order_id_str)

    # Get order for price bounds
    order = await offer_dispatch_service.order_repo.get_by_id(order_id)
    if order is None:
        await state.clear()
        return

    offer_price = Decimal(str(order.price))
    max_price = offer_price * 10

    # Parse and validate
    try:
        desired = Decimal(message.text.strip().replace(",", "."))
    except InvalidOperation:
        desired = None

    if desired is None or desired < offer_price or desired > max_price:
        # Resolve currency symbol
        currency = getattr(order, "currency", None) or ""
        country_repo = getattr(offer_dispatch_service, "country_repo", None)
        symbol = offer_dispatch_service.currency_symbol
        if country_repo and currency:
            country = await country_repo.get_by_currency_code(currency)
            if country:
                symbol = country.currency_symbol
        msg = await bot_texts_service.get("msg_invalid_price", locale)
        error_text = msg.format(min=offer_price, max=max_price, currency=symbol)
        await messenger_client.send_text(chat_id=str(message.chat.id), text=error_text)
        return

    # Valid price — record skip
    user = await user_role_service.get_user_by_external_id(str(message.from_user.id))
    if user is None:
        await state.clear()
        return

    result = await offer_dispatch_service.record_skip(
        order_id, user.user_id,
        rejection_reason=RejectionReason.LOW_PRICE,
        desired_price=desired,
    )
    await state.clear()

    # Resolve currency symbol for confirmation
    currency = getattr(order, "currency", None) or ""
    country_repo = getattr(offer_dispatch_service, "country_repo", None)
    symbol = offer_dispatch_service.currency_symbol
    if country_repo and currency:
        country_obj = await country_repo.get_by_currency_code(currency)
        if country_obj:
            symbol = country_obj.currency_symbol

    # Confirmation message
    msg = await bot_texts_service.get("msg_offer_skipped_low_price", locale)
    confirmation = msg.format(price=desired, currency=symbol)
    await messenger_client.send_text(chat_id=str(message.chat.id), text=confirmation)

    # Notify manager if needed
    if result.manager_id:
        manager = await user_role_service.get_user_by_id(result.manager_id)
        if manager and manager.external_id and manager.external_id.isdigit():
            mgr_locale = manager.language or "ru"
            notification_msg = await bot_texts_service.get(
                "msg_manager_low_price_notification", mgr_locale
            )
            blogger_name = user.username or user.external_id
            notification = notification_msg.format(
                blogger=blogger_name,
                order=order.offer_text[:50] if order.offer_text else str(order_id)[:8],
                desired_price=desired,
                offer_price=result.order_price or offer_price,
                currency=symbol,
            )
            await send_with_retry(
                messenger_client,
                chat_id=manager.external_id,
                text=notification,
                retries=_send_retries,
                delay_seconds=_send_retry_delay_seconds,
                logger=logger,
                extra={"order_id": str(order_id)},
            )
```

Add `Message` to imports from `aiogram.types`.

- [ ] **Step 7: Add `handle_cancel_price_entry` handler**

```python
@router.callback_query(
    lambda callback: callback.data and callback.data.startswith("orr_cancel:")
)
async def handle_cancel_price_entry(
    callback: CallbackQuery,
    state: FSMContext,
    user_role_service: UserRoleService,
    offer_dispatch_service: OfferDispatchService,
    bot_texts_service: BotTextsService,
    user_locale: str = "ru",
    messenger_client: MessengerClient | None = None,
    event_adapter: MessengerEventAdapter | None = None,
) -> None:
    """Cancel price entry — record skip without reason."""
    messenger_client, event_adapter = resolve_messenger_dependencies(
        callback, messenger_client, event_adapter
    )
    incoming = event_adapter.from_callback(callback)
    locale = user_locale
    await state.clear()

    # Parse order_id from orr_cancel:{hex}
    raw = (callback.data or "").split(":", 1)
    order_id: UUID | None = None
    if len(raw) == 2:
        try:
            order_id = UUID(raw[1])
        except ValueError:
            pass

    user = await get_user_and_ensure_allowed_callback(
        incoming, messenger_client, user_role_service,
        user_not_found_msg="", blocked_msg="", pause_msg="",
    )
    if user is not None and order_id is not None:
        await offer_dispatch_service.record_skip(order_id, user.user_id)

    if incoming.message_id:
        with contextlib.suppress(Exception):
            await messenger_client.edit_reply_markup(
                chat_id=incoming.chat_id, message_id=incoming.message_id, keyboard=None,
            )
    msg = await bot_texts_service.get("msg_price_entry_cancelled", locale)
    await messenger_client.answer_callback(callback_id=incoming.callback_id, text=msg or "")
```

- [ ] **Step 8: Run tests**

```bash
uv run pytest tests/bot/handlers/test_offer_responses.py -v
```

Expected: all tests PASS (new and existing).

- [ ] **Step 9: Commit**

```bash
git add src/ugc_bot/bot/handlers/offer_responses.py tests/bot/handlers/test_offer_responses.py
git commit -m "feat: add rejection reason selection and price entry FSM handlers"
```

---

### Task 8: Admin panel — Add rejection columns

**Files:**
- Modify: `src/ugc_bot/admin/app.py:1648-1671`

- [ ] **Step 1: Add `rejection_reason` and `desired_price` to `OfferDispatchAdmin`**

Add to `column_list`:
```python
OfferDispatchModel.rejection_reason,
OfferDispatchModel.desired_price,
```

Add to `column_labels`:
```python
OfferDispatchModel.rejection_reason: "Причина отказа",
OfferDispatchModel.desired_price: "Желаемая цена",
```

Add `column_searchable_list` with `rejection_reason` for filtering.

- [ ] **Step 2: Commit**

```bash
git add src/ugc_bot/admin/app.py
git commit -m "feat: add rejection_reason and desired_price to admin panel"
```

---

### Task 9: Full verification

- [ ] **Step 1: Run full quality checks**

```bash
make fix
```

Expected: format + lint + typecheck + coverage all pass.

- [ ] **Step 2: Run full test suite**

```bash
make test
```

Expected: all tests pass, coverage ≥ 98%.

- [ ] **Step 3: Fix any issues found**

If tests or linting fail, fix and re-run.

- [ ] **Step 4: Final commit if any fixes**

```bash
git add -A
git commit -m "fix: address linting and test issues for rejection reasons"
```
