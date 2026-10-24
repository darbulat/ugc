"""One-shot native Telegram invoice link creation, without transport retries."""

from decimal import Decimal

from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
from aiogram.types import LabeledPrice

from ugc_bot.application.services.payment_service import (
    build_receipt_provider_data,
)
from ugc_bot.domain.checkout import LinkRejected, PreparedInvoice, invoice_url


class TelegramInvoiceLinks:
    def __init__(self, bot: Bot, provider_token: str, receipt_description: str):
        self.bot = bot
        self.provider_token = provider_token
        self.receipt_description = receipt_description

    async def create_link(self, invoice: PreparedInvoice) -> str:
        if (
            not self.provider_token.strip()
            or invoice.currency != "RUB"
            or type(invoice.selection_minor) is not int
            or type(invoice.accompaniment_minor) is not int
            or invoice.selection_minor <= 0
            or invoice.accompaniment_minor < 0
            or invoice.total_minor > 100_000_000
        ):
            raise LinkRejected("invalid_configured_invoice")
        prices = [
            LabeledPrice(
                label="UMC: подбор / selection", amount=invoice.selection_minor
            )
        ]
        if invoice.accompaniment_minor:
            prices.append(
                LabeledPrice(
                    label="UMC: сопровождение / accompaniment",
                    amount=invoice.accompaniment_minor,
                )
            )
        try:
            link = await self.bot.create_invoice_link(
                title="Use My Content",
                description=invoice.description.strip()[:255]
                or "Услуги платформы UMC",
                payload=str(invoice.order_id),
                provider_token=self.provider_token,
                currency=invoice.currency,
                prices=prices,
                provider_data=build_receipt_provider_data(
                    Decimal(invoice.total_minor) / 100,
                    invoice.currency,
                    self.receipt_description,
                ),
                need_email=True,
                send_email_to_provider=True,
                request_timeout=8,
            )
        except (
            TelegramBadRequest,
            TelegramForbiddenError,
            TelegramRetryAfter,
        ) as exc:
            raise LinkRejected("invoice_provider_rejected") from exc
        return invoice_url(link)
