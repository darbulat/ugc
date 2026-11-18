"""Explicit operator handoff; no allocation, automatic retries or billing."""

from dataclasses import dataclass
from typing import Protocol

from ugc_bot.application.creator_offer_cards import (
    client_contact_links,
    client_contact_text,
)
from ugc_bot.application.financial_ports import Clock
from ugc_bot.application.notice_delivery_ports import (
    DeliveryFailure,
    NoticeReceiptTransport,
    ReceiptCard,
    ReceiptLink,
)
from ugc_bot.application.ports import TransactionManager


@dataclass(frozen=True)
class TransferMessage:
    address: str
    text: str
    card: ReceiptCard
    channel: str = "telegram"
    address_kind: str = "chat_id"
    action_url: str | None = None
    action_label: str | None = None


class TransferRepository(Protocol):
    async def prepare(self, db, order_id, creator_id, operator, at): ...
    async def finish(self, db, attempt, state, at, reference, reason): ...


@dataclass
class CreatorTransferService:
    repository: TransferRepository
    transactions: TransactionManager
    transport: NoticeReceiptTransport
    clock: Clock

    async def send(self, order_id, creator_id, *, operator):
        async with self.transactions.transaction() as db:
            state, attempt = await self.repository.prepare(
                db, order_id, creator_id, operator, self.clock.now()
            )
        if attempt is None:
            return state
        try:
            contact = attempt["contact"]
            text = client_contact_text(
                order_title=attempt["title"],
                name=contact["name"],
                phone=contact["phone"],
                locale="ru",
            )
            price = (
                f"{attempt['requested_price']:,.2f}".replace(",", " ")
                .replace(".", ",")
                .removesuffix(",00")
            )
            symbol = (
                "₽" if attempt["currency"] == "RUB" else attempt["currency"]
            )
            text += f"\nПредложенная цена: {price} {symbol}."
            if attempt["source"] == "counteroffer":
                text += "\nЦена требует согласования с вами."
            links = client_contact_links(
                profile=contact["instagram"],
                handle=contact["telegram"],
                locale="ru",
            )
            message = TransferMessage(
                str(attempt["address"]),
                text,
                ReceiptCard(
                    tuple(ReceiptLink(label, url) for label, url in links)
                ),
            )
            receipt = await self.transport.send(message)
            if receipt.channel != "telegram" or not receipt.reference:
                raise DeliveryFailure(
                    "delivery_receipt_invalid", uncertain=True
                )
            state, reference, reason = "sent", receipt.reference, None
        except DeliveryFailure as exc:
            state, reference, reason = (
                ("unknown" if exc.uncertain else "failed"),
                None,
                exc.code,
            )
        except Exception:
            state, reference, reason = (
                "unknown",
                None,
                "delivery_result_unknown",
            )
        async with self.transactions.transaction() as db:
            applied = await self.repository.finish(
                db, attempt, state, self.clock.now(), reference, reason
            )
        return state if applied else "unknown"
