"""Telegram payment provider implementation."""

from aiogram import Bot

from ugc_bot.application.messenger.ports import PaymentProvider


class TelegramPaymentProvider(PaymentProvider):
    """Payment provider backed by aiogram Bot."""

    def __init__(self, bot: Bot) -> None:
        """Initialize with aiogram Bot."""
        self._bot = bot

    async def confirm_pre_checkout(self, *, query_id: str) -> None:
        """Confirm pre-checkout query."""
        await self._bot.answer_pre_checkout_query(
            pre_checkout_query_id=query_id, ok=True
        )

    async def reject_pre_checkout(
        self, *, query_id: str, error_message: str
    ) -> None:
        """Reject pre-checkout query with error message."""
        await self._bot.answer_pre_checkout_query(
            pre_checkout_query_id=query_id,
            ok=False,
            error_message=error_message,
        )
