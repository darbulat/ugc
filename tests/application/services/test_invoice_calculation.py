"""Tests for calculate_invoice_total."""

from decimal import Decimal

from ugc_bot.application.services.payment_service import (
    calculate_invoice_total,
)


class TestCalculateInvoiceTotal:
    def test_ru_returns_contact_pricing_only(self):
        result = calculate_invoice_total(
            contact_pricing_price=Decimal("300"),
            order_price=Decimal("1000"),
            bloggers_needed=5,
            tax_rate=Decimal("0"),
            is_ru=True,
        )
        assert result == Decimal("300")

    def test_intl_basic_formula(self):
        # (300 + 1000 * 3) * (1 + 0.12) = 3300 * 1.12 = 3696
        result = calculate_invoice_total(
            contact_pricing_price=Decimal("300"),
            order_price=Decimal("1000"),
            bloggers_needed=3,
            tax_rate=Decimal("0.12"),
            is_ru=False,
        )
        assert result == Decimal("3696.00")

    def test_intl_zero_tax(self):
        # (300 + 1000 * 3) * (1 + 0) = 3300
        result = calculate_invoice_total(
            contact_pricing_price=Decimal("300"),
            order_price=Decimal("1000"),
            bloggers_needed=3,
            tax_rate=Decimal("0"),
            is_ru=False,
        )
        assert result == Decimal("3300.00")

    def test_intl_zero_order_price(self):
        # (300 + 0 * 3) * (1 + 0.1) = 300 * 1.1 = 330
        result = calculate_invoice_total(
            contact_pricing_price=Decimal("300"),
            order_price=Decimal("0"),
            bloggers_needed=3,
            tax_rate=Decimal("0.1"),
            is_ru=False,
        )
        assert result == Decimal("330.00")

    def test_intl_rounding(self):
        # (100 + 33.33 * 3) * (1 + 0.07) = 199.99 * 1.07 = 213.9893
        result = calculate_invoice_total(
            contact_pricing_price=Decimal("100"),
            order_price=Decimal("33.33"),
            bloggers_needed=3,
            tax_rate=Decimal("0.07"),
            is_ru=False,
        )
        assert result == Decimal("213.99")
