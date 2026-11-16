"""Receipt-aware durable workflow delivery with a fresh pre-transport check."""

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlencode, urlsplit
from uuid import UUID

from ugc_bot.application.customer_offer_texts import offer_text
from ugc_bot.application.customer_request_admin_text import message_units
from ugc_bot.application.customer_workflow_ports import (
    CustomerWorkflowRepository,
)
from ugc_bot.application.customer_workflow_texts import FOLLOWUP_TEXTS
from ugc_bot.application.financial_ports import Clock
from ugc_bot.application.notice_delivery_ports import (
    DeliveryFailure,
    NoticeReceiptTransport,
    ReceiptCard,
    ReceiptLink,
)
from ugc_bot.application.order_summary_admin_text import (
    is_order_summary_review,
    order_summary_admin_text,
)
from ugc_bot.application.ports import TransactionManager
from ugc_bot.application.services.business_order_card import order_card_url
from ugc_bot.domain.financial import utc

_DESTINATION_FIELDS = (
    "channel",
    "address",
    "address_kind",
    "language",
    "order_id",
    "requester_telegram_id",
)


def _is_rate_limit(exc: DeliveryFailure) -> bool:
    return not exc.uncertain and exc.retry_after_seconds is not None


class Texts(Protocol):
    async def get(self, key: str, locale: str | None = None) -> str: ...


@dataclass(frozen=True)
class WorkflowMessage:
    job_id: UUID
    channel: str
    address: str
    address_kind: str
    text: str
    action_url: str | None = None
    action_label: str | None = None
    card: ReceiptCard | None = None


@dataclass
class CustomerWorkflowDelivery:
    repository: CustomerWorkflowRepository
    transactions: TransactionManager
    transport: NoticeReceiptTransport
    clock: Clock
    action_urls: dict[str, str]
    texts: Texts | None = None
    lease_seconds: int = 120
    followups_enabled: bool = True
    offer_loader: Callable[[dict], Awaitable[dict | None]] | None = None
    admin_base_url: str = ""

    async def prepare(self) -> dict | None:
        async with self.transactions.transaction() as session:
            now = utc(self.clock.now())
            await self.repository.expand_admin(now, session=session)
            return await self.repository.claim(
                now,
                self.lease_seconds,
                session=session,
                include_followups=self.followups_enabled,
            )

    async def _message(self, current: dict) -> WorkflowMessage:
        url, label = None, None
        card = None
        if current["request_id"]:
            text = current["text"]
            if is_order_summary_review(current):
                text = order_summary_admin_text(current)
                if current.get("order_id"):
                    text = self._with_admin_order_link(
                        text, current["order_id"]
                    )
            elif current.get("kind") in ("support", "service"):
                text, card = self._admin_card(current)
        else:
            stage, locale = current["stage"], current["language"]
            defaults = FOLLOWUP_TEXTS.get(locale, FOLLOWUP_TEXTS["ru"])
            text, label = defaults[stage - 1], defaults[3]
            if self.texts:
                text = (
                    await self.texts.get(f"customer_followup_{stage}", locale)
                    or text
                )
                label = (
                    await self.texts.get("customer_followup_action", locale)
                    or label
                )
            if self.offer_loader:
                offer = await self.offer_loader(current)
                if offer:
                    text += "\n\n" + offer_text(offer, locale)
            base = self.action_urls.get(current["channel"], "")
            if not base:
                raise DeliveryFailure(
                    "followup_action_unavailable", uncertain=False
                )
            query = {"screen": "services" if stage == 3 else "orders"}
            if current["order_id"]:
                query["order_id"] = str(current["order_id"])
            url = base + ("&" if "?" in base else "?") + urlencode(query)
        return WorkflowMessage(
            current["job_id"],
            current["channel"],
            current["address"],
            current["address_kind"],
            text,
            url,
            label,
            card,
        )

    def _admin_order_url(self, order_id: UUID) -> str | None:
        base = order_card_url(self.admin_base_url)
        if not base:
            return None
        parsed = urlsplit(base)
        if parsed.query or parsed.fragment:
            return None
        base = base.rstrip("/")
        if not parsed.path.strip("/"):
            base += "/admin"
        return f"{base}/orders/{order_id}"

    def _with_admin_order_link(self, text: str, order_id: UUID) -> str:
        if url := self._admin_order_url(order_id):
            linked = f"{text}\n\nКарточка заказа: {url}"
            if message_units(linked) <= 4000:
                return linked
        return text

    def _admin_card(self, current: dict) -> tuple[str, ReceiptCard]:
        text = current["text"]
        links = []
        if not current["part"]:
            if order_id := current.get("order_id"):
                url = self._admin_order_url(order_id)
                if url and url.startswith("https://") and len(url) <= 2048:
                    links.append(ReceiptLink("Открыть заказ", url))
                else:
                    text = self._with_admin_order_link(text, order_id)
            requester = current.get("requester_telegram_id")
            if (
                current["channel"] == "telegram"
                and isinstance(requester, str)
                and re.fullmatch(r"[1-9][0-9]{0,15}", requester)
            ):
                links.append(
                    ReceiptLink("Профиль клиента", f"tg://user?id={requester}")
                )
        return text, ReceiptCard(tuple(links))

    async def _retry_rate_limit(self, job: dict, delay: int) -> None:
        async with self.transactions.transaction() as session:
            await self.repository.retry_before_transport(
                job,
                utc(self.clock.now()),
                session=session,
                retry_after_seconds=delay,
            )

    async def deliver(self, job: dict) -> bool:
        # Preparation is committed; this fresh read also catches
        # activity/payment
        # occurring between claim and dispatch. No transaction spans
        # provider I/O.
        async with self.transactions.transaction() as session:
            current = await self.repository.eligible(
                job, utc(self.clock.now()), session=session, mark_sending=False
            )
            if current is None:
                await self.repository.finish(
                    job,
                    "obsolete",
                    None,
                    "delivery_no_longer_eligible",
                    session=session,
                )
                return False
        try:
            message = await self._message(current)
        except Exception:
            async with self.transactions.transaction() as session:
                await self.repository.retry_preparation(
                    job, utc(self.clock.now()), session=session
                )
            return True

        # Local preparation can perform I/O. Recheck after it and transition
        # to sending in the same transaction as the final eligibility read.
        async with self.transactions.transaction() as session:
            refreshed = await self.repository.eligible(
                job, utc(self.clock.now()), session=session, mark_sending=False
            )
            if refreshed is None:
                await self.repository.finish(
                    job,
                    "obsolete",
                    None,
                    "delivery_no_longer_eligible",
                    session=session,
                )
                return False
            if any(
                refreshed.get(key) != current.get(key)
                for key in _DESTINATION_FIELDS
            ):
                await self.repository.retry_preparation(
                    job, utc(self.clock.now()), session=session
                )
                return False
            # The locks acquired by the preceding eligibility read stay held
            # until this transaction commits, including the sending marker.
            started = await self.repository.eligible(
                job, utc(self.clock.now()), session=session, mark_sending=True
            )
            if started is None:
                return False
            if any(
                started.get(key) != current.get(key)
                for key in _DESTINATION_FIELDS
            ):
                await self.repository.retry_before_transport(
                    job, utc(self.clock.now()), session=session
                )
                return False
        return await self._send_message(job, current, message)

    async def _send_message(
        self, job: dict, current: dict, message: WorkflowMessage
    ) -> bool:
        state, reference, reason = "accepted", None, None
        try:
            receipt = await self.transport.send(message)
            if (
                receipt.channel != current["channel"]
                or not receipt.reference.strip()
            ):
                raise DeliveryFailure(
                    "workflow_receipt_invalid", uncertain=True
                )
            reference = receipt.reference
        except DeliveryFailure as exc:
            if _is_rate_limit(exc):
                await self._retry_rate_limit(job, exc.retry_after_seconds or 0)
                return True
            state, reason = ("unknown" if exc.uncertain else "failed"), exc.code
        except Exception:
            state, reason = "unknown", "workflow_result_unknown"
        async with self.transactions.transaction() as session:
            await self.repository.finish(
                job, state, reference, reason, session=session
            )
        return True

    async def run_once(self, limit: int = 100) -> int:
        if not 1 <= limit <= 1000 or self.lease_seconds < 1:
            raise ValueError("workflow_batch_invalid")
        attempted = 0
        for _ in range(limit):
            job = await self.prepare()
            if job is None:
                break
            attempted += await self.deliver(job)
        return attempted
