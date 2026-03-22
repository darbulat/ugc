"""Tests for ReferralService."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy.exc import IntegrityError

from ugc_bot.application.services.referral_service import ReferralService
from ugc_bot.domain.entities import (
    User,
    UserReferralBinding,
    UserReferralPending,
)
from ugc_bot.domain.enums import MessengerType, UserStatus
from ugc_bot.infrastructure.memory_repositories import (
    InMemoryUserReferralBindingRepository,
    InMemoryUserReferralPendingRepository,
    InMemoryUserRepository,
)


def test_parse_referral_code_returns_none_for_empty() -> None:
    """parse_referral_code returns None for empty or None."""
    service = ReferralService(
        user_repo=object(),
        user_referral_pending_repo=object(),
        user_referral_binding_repo=object(),
        transaction_manager=None,
    )
    assert service.parse_referral_code(None) is None
    assert service.parse_referral_code("") is None
    assert service.parse_referral_code("   ") is None


def test_parse_referral_code_returns_none_for_plain_start() -> None:
    """parse_referral_code returns None for /start without payload."""
    service = ReferralService(
        user_repo=object(),
        user_referral_pending_repo=object(),
        user_referral_binding_repo=object(),
        transaction_manager=None,
    )
    assert service.parse_referral_code("/start") is None


def test_parse_referral_code_extracts_code() -> None:
    """parse_referral_code extracts code from /start ref_XXX."""
    service = ReferralService(
        user_repo=object(),
        user_referral_pending_repo=object(),
        user_referral_binding_repo=object(),
        transaction_manager=None,
    )
    assert service.parse_referral_code("/start ref_abc123") == "abc123"
    assert service.parse_referral_code("/start ref_xyz") == "xyz"


def test_parse_referral_code_returns_none_when_payload_not_ref_prefix() -> None:
    """parse_referral_code returns None when payload is not ref_*."""
    service = ReferralService(
        user_repo=object(),
        user_referral_pending_repo=object(),
        user_referral_binding_repo=object(),
        transaction_manager=None,
    )
    assert service.parse_referral_code("/start foo") is None


def test_parse_referral_code_returns_none_when_only_ref_prefix() -> None:
    """parse_referral_code returns None when payload is ref_ with no code."""
    service = ReferralService(
        user_repo=object(),
        user_referral_pending_repo=object(),
        user_referral_binding_repo=object(),
        transaction_manager=None,
    )
    assert service.parse_referral_code("/start ref_") is None
    assert service.parse_referral_code("/start ref_   ") is None


@pytest.mark.asyncio
async def test_save_pending_referral_when_referrer_exists() -> None:
    """save_pending_referral saves pending when user with code exists."""
    user_repo = InMemoryUserRepository()
    referrer = User(
        user_id=uuid4(),
        telegram_id="ref",
        messenger_type=MessengerType.TELEGRAM,
        username="referrer",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        referral_code="abc123",
    )
    await user_repo.save(referrer)

    referred_id = uuid4()
    pending_repo = InMemoryUserReferralPendingRepository()
    binding_repo = InMemoryUserReferralBindingRepository()

    service = ReferralService(
        user_repo=user_repo,
        user_referral_pending_repo=pending_repo,
        user_referral_binding_repo=binding_repo,
        transaction_manager=None,
    )
    result = await service.save_pending_referral(referred_id, "abc123")
    assert result is True
    pending = await pending_repo.get_by_user(referred_id)
    assert pending is not None
    assert pending.referrer_user_id == referrer.user_id
    assert pending.user_id == referred_id


@pytest.mark.asyncio
async def test_save_pending_referral_when_code_unknown_returns_false() -> None:
    """save_pending_referral returns False when referral code not found."""
    user_repo = InMemoryUserRepository()
    pending_repo = InMemoryUserReferralPendingRepository()
    service = ReferralService(
        user_repo=user_repo,
        user_referral_pending_repo=pending_repo,
        user_referral_binding_repo=InMemoryUserReferralBindingRepository(),
        transaction_manager=None,
    )
    result = await service.save_pending_referral(uuid4(), "unknown")
    assert result is False


@pytest.mark.asyncio
async def test_save_pending_referral_self_referral_returns_false() -> None:
    """save_pending_referral returns False when user uses own referral code."""
    user_repo = InMemoryUserRepository()
    user_id = uuid4()
    user = User(
        user_id=user_id,
        telegram_id="me",
        messenger_type=MessengerType.TELEGRAM,
        username="me",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        referral_code="mycode",
    )
    await user_repo.save(user)

    pending_repo = InMemoryUserReferralPendingRepository()
    binding_repo = InMemoryUserReferralBindingRepository()
    service = ReferralService(
        user_repo=user_repo,
        user_referral_pending_repo=pending_repo,
        user_referral_binding_repo=binding_repo,
        transaction_manager=None,
    )
    result = await service.save_pending_referral(user_id, "mycode")
    assert result is False
    assert await pending_repo.get_by_user(user_id) is None


@pytest.mark.asyncio
async def test_save_pending_referral_when_pending_exists_returns_true() -> None:
    """save_pending_referral returns True when user already has pending."""
    user_repo = InMemoryUserRepository()
    referrer = User(
        user_id=uuid4(),
        telegram_id="r",
        messenger_type=MessengerType.TELEGRAM,
        username="ref",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        referral_code="code1",
    )
    await user_repo.save(referrer)
    referred_id = uuid4()
    pending_repo = InMemoryUserReferralPendingRepository()
    await pending_repo.save(
        UserReferralPending(
            user_id=referred_id,
            referrer_user_id=referrer.user_id,
            created_at=datetime.now(timezone.utc),
        )
    )
    service = ReferralService(
        user_repo=user_repo,
        user_referral_pending_repo=pending_repo,
        user_referral_binding_repo=InMemoryUserReferralBindingRepository(),
        transaction_manager=None,
    )
    result = await service.save_pending_referral(referred_id, "code1")
    assert result is True


@pytest.mark.asyncio
async def test_save_pending_referral_skips_if_already_bound() -> None:
    """Returns True and does not create pending if user already has binding."""
    user_repo = InMemoryUserRepository()
    referrer = User(
        user_id=uuid4(),
        telegram_id="r",
        messenger_type=MessengerType.TELEGRAM,
        username="ref",
        status=UserStatus.ACTIVE,
        issue_count=0,
        created_at=datetime.now(timezone.utc),
        referral_code="code1",
    )
    await user_repo.save(referrer)
    referred_id = uuid4()
    pending_repo = InMemoryUserReferralPendingRepository()
    binding_repo = InMemoryUserReferralBindingRepository()
    await binding_repo.save(
        UserReferralBinding(
            referrer_user_id=referrer.user_id,
            referred_user_id=referred_id,
            created_at=datetime.now(timezone.utc),
        )
    )
    service = ReferralService(
        user_repo=user_repo,
        user_referral_pending_repo=pending_repo,
        user_referral_binding_repo=binding_repo,
        transaction_manager=None,
    )
    result = await service.save_pending_referral(referred_id, "code1")
    assert result is True
    assert await pending_repo.get_by_user(referred_id) is None


@pytest.mark.asyncio
async def test_create_binding_from_pending_creates_binding() -> None:
    """create_binding_from_pending creates binding and deletes pending."""
    referrer_id = uuid4()
    referred_id = uuid4()
    now = datetime.now(timezone.utc)
    pending_repo = InMemoryUserReferralPendingRepository()
    await pending_repo.save(
        UserReferralPending(
            user_id=referred_id,
            referrer_user_id=referrer_id,
            created_at=now,
        )
    )
    binding_repo = InMemoryUserReferralBindingRepository()
    service = ReferralService(
        user_repo=InMemoryUserRepository(),
        user_referral_pending_repo=pending_repo,
        user_referral_binding_repo=binding_repo,
        transaction_manager=None,
    )
    binding = await service.create_binding_from_pending(referred_id)
    assert binding is not None
    assert binding.referrer_user_id == referrer_id
    assert binding.referred_user_id == referred_id
    assert await pending_repo.get_by_user(referred_id) is None


@pytest.mark.asyncio
async def test_create_binding_from_pending_when_no_pending_returns_none() -> (
    None
):
    """create_binding_from_pending returns None when no pending for user."""
    pending_repo = InMemoryUserReferralPendingRepository()
    service = ReferralService(
        user_repo=InMemoryUserRepository(),
        user_referral_pending_repo=pending_repo,
        user_referral_binding_repo=InMemoryUserReferralBindingRepository(),
        transaction_manager=None,
    )
    result = await service.create_binding_from_pending(uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_create_binding_from_pending_existing_returns_it() -> None:
    """create_binding_from_pending returns existing binding, deletes pending."""
    referrer_id = uuid4()
    referred_id = uuid4()
    now = datetime.now(timezone.utc)
    pending_repo = InMemoryUserReferralPendingRepository()
    await pending_repo.save(
        UserReferralPending(
            user_id=referred_id,
            referrer_user_id=referrer_id,
            created_at=now,
        )
    )
    binding_repo = InMemoryUserReferralBindingRepository()
    existing_binding = UserReferralBinding(
        referrer_user_id=referrer_id,
        referred_user_id=referred_id,
        created_at=now,
    )
    await binding_repo.save(existing_binding)
    service = ReferralService(
        user_repo=InMemoryUserRepository(),
        user_referral_pending_repo=pending_repo,
        user_referral_binding_repo=binding_repo,
        transaction_manager=None,
    )
    result = await service.create_binding_from_pending(referred_id)
    assert result is not None
    assert result.referrer_user_id == referrer_id
    assert result.referred_user_id == referred_id
    assert await pending_repo.get_by_user(referred_id) is None


@pytest.mark.asyncio
async def test_create_binding_from_pending_with_session_uses_session() -> None:
    """create_binding_from_pending with session bypasses transaction_manager."""
    referrer_id = uuid4()
    referred_id = uuid4()
    now = datetime.now(timezone.utc)
    pending_repo = InMemoryUserReferralPendingRepository()
    await pending_repo.save(
        UserReferralPending(
            user_id=referred_id,
            referrer_user_id=referrer_id,
            created_at=now,
        )
    )
    binding_repo = InMemoryUserReferralBindingRepository()
    service = ReferralService(
        user_repo=InMemoryUserRepository(),
        user_referral_pending_repo=pending_repo,
        user_referral_binding_repo=binding_repo,
        transaction_manager=None,
    )
    session = object()
    result = await service.create_binding_from_pending(
        referred_id, session=session
    )
    assert result is not None
    assert result.referred_user_id == referred_id


@pytest.mark.asyncio
async def test_create_binding_integrity_error_returns_existing() -> None:
    """On IntegrityError (race), return existing binding and delete pending."""
    referrer_id = uuid4()
    referred_id = uuid4()
    now = datetime.now(timezone.utc)
    pending_repo = InMemoryUserReferralPendingRepository()
    await pending_repo.save(
        UserReferralPending(
            user_id=referred_id,
            referrer_user_id=referrer_id,
            created_at=now,
        )
    )
    existing_binding = UserReferralBinding(
        referrer_user_id=referrer_id,
        referred_user_id=referred_id,
        created_at=now,
    )
    binding_repo = InMemoryUserReferralBindingRepository()
    get_calls = []

    async def get_by_referred_user(referred_user_id, session=None):
        get_calls.append(1)
        return existing_binding if len(get_calls) > 1 else None

    async def save_raise_integrity(binding: UserReferralBinding, session=None):
        raise IntegrityError("", "", "")

    binding_repo.get_by_referred_user = AsyncMock(
        side_effect=get_by_referred_user
    )
    binding_repo.save = AsyncMock(side_effect=save_raise_integrity)

    service = ReferralService(
        user_repo=InMemoryUserRepository(),
        user_referral_pending_repo=pending_repo,
        user_referral_binding_repo=binding_repo,
        transaction_manager=None,
    )
    result = await service.create_binding_from_pending(referred_id)
    assert result is not None
    assert result.referrer_user_id == referrer_id
    assert result.referred_user_id == referred_id
    assert await pending_repo.get_by_user(referred_id) is None
