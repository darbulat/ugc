"""Tests for PaymentService.calculate_invoice_data."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from ugc_bot.application.services.payment_service import InvoiceData
from ugc_bot.domain.entities import ContactPricing, Country
from ugc_bot.domain.enums import OrderStatus
from tests.helpers.factories import create_test_order, create_test_user
from tests.helpers.services import build_payment_service

NOW = datetime.now(timezone.utc)


@pytest.fixture
def patched_config(monkeypatch):
    """Config with provider tokens set."""
    monkeypatch.setenv("TELEGRAM_PROVIDER_TOKEN", "ru_provider")
    monkeypatch.setenv("TELEGRAM_PROVIDER_TOKEN_INTL", "intl_provider")
    from ugc_bot.config import load_config

    return load_config()


@pytest.mark.asyncio
async def test_calculate_invoice_data_ru(
    user_repo,
    advertiser_repo,
    order_repo,
    payment_repo,
    pricing_repo,
    country_repo,
    fake_tm,
    patched_config,
):
    """RU user gets contact_pricing only, with YooKassa receipt."""
    pricing_repo.prices[("ru", 3)] = ContactPricing(
        country_code="ru",
        bloggers_count=3,
        price=Decimal("300"),
        currency="RUB",
        updated_at=NOW,
    )
    user = await create_test_user(
        user_repo,
        external_id="1",
        country="ru",
    )
    order = await create_test_order(
        order_repo,
        user.user_id,
        price=1000.0,
        bloggers_needed=3,
        status=OrderStatus.NEW,
    )
    service = build_payment_service(
        user_repo,
        advertiser_repo,
        order_repo,
        payment_repo,
        pricing_repo,
        fake_tm,
        country_repo=country_repo,
    )
    result = await service.calculate_invoice_data(
        order,
        "ru",
        patched_config,
    )
    assert result is not None
    assert result.total == Decimal("300")
    assert result.currency == "RUB"
    assert result.provider_token == "ru_provider"
    assert result.provider_data is not None  # 54-FZ receipt
    assert result.is_ru is True
    assert result.need_email is True


@pytest.mark.asyncio
async def test_calculate_invoice_data_intl(
    user_repo,
    advertiser_repo,
    order_repo,
    payment_repo,
    pricing_repo,
    country_repo,
    fake_tm,
    patched_config,
):
    """International user gets full formula with tax."""
    country_repo.countries["ge"] = Country(
        code="ge",
        name_native="საქართველო",
        currency_code="GEL",
        currency_symbol="₾",
        locale="en",
        tax_rate=Decimal("0.18"),
    )
    pricing_repo.prices[("ge", 3)] = ContactPricing(
        country_code="ge",
        bloggers_count=3,
        price=Decimal("200"),
        currency="GEL",
        updated_at=NOW,
    )
    user = await create_test_user(
        user_repo,
        external_id="2",
        country="ge",
    )
    order = await create_test_order(
        order_repo,
        user.user_id,
        price=500.0,
        bloggers_needed=3,
        status=OrderStatus.NEW,
    )
    service = build_payment_service(
        user_repo,
        advertiser_repo,
        order_repo,
        payment_repo,
        pricing_repo,
        fake_tm,
        country_repo=country_repo,
    )
    result = await service.calculate_invoice_data(
        order,
        "ge",
        patched_config,
    )
    assert result is not None
    # (200 + 500 * 3) * (1 + 0.18) = 1700 * 1.18 = 2006.00
    assert result.total == Decimal("2006.00")
    assert result.currency == "GEL"
    assert result.currency_symbol == "₾"
    assert result.provider_token == "intl_provider"
    assert result.provider_data is None
    assert result.is_ru is False
    assert result.need_email is False


@pytest.mark.asyncio
async def test_calculate_invoice_data_no_pricing(
    user_repo,
    advertiser_repo,
    order_repo,
    payment_repo,
    pricing_repo,
    country_repo,
    fake_tm,
    patched_config,
):
    """Returns None when pricing not configured for country."""
    user = await create_test_user(user_repo, external_id="3", country="ge")
    order = await create_test_order(
        order_repo,
        user.user_id,
        price=500.0,
        bloggers_needed=3,
        status=OrderStatus.NEW,
    )
    service = build_payment_service(
        user_repo,
        advertiser_repo,
        order_repo,
        payment_repo,
        pricing_repo,
        fake_tm,
        country_repo=country_repo,
    )
    result = await service.calculate_invoice_data(
        order,
        "ge",
        patched_config,
    )
    assert result is None


@pytest.mark.asyncio
async def test_calculate_invoice_data_none_country_defaults_to_ru(
    user_repo,
    advertiser_repo,
    order_repo,
    payment_repo,
    pricing_repo,
    country_repo,
    fake_tm,
    patched_config,
):
    """user_country=None is treated as RU."""
    pricing_repo.prices[("ru", 3)] = ContactPricing(
        country_code="ru",
        bloggers_count=3,
        price=Decimal("300"),
        currency="RUB",
        updated_at=NOW,
    )
    user = await create_test_user(user_repo, external_id="4")
    order = await create_test_order(
        order_repo,
        user.user_id,
        price=1000.0,
        bloggers_needed=3,
        status=OrderStatus.NEW,
    )
    service = build_payment_service(
        user_repo,
        advertiser_repo,
        order_repo,
        payment_repo,
        pricing_repo,
        fake_tm,
        country_repo=country_repo,
    )
    result = await service.calculate_invoice_data(
        order,
        None,
        patched_config,
    )
    assert result is not None
    assert result.total == Decimal("300")
    assert result.is_ru is True
