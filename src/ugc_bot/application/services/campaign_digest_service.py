"""Committed summary/start -> one-shot I/O -> fenced immutable observation."""

from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import uuid4

from ugc_bot.application.campaign_digest_ports import (
    CampaignDigestRepository,
    DigestAttempt,
)
from ugc_bot.application.collaboration_ports import canonical
from ugc_bot.application.financial_ports import Clock
from ugc_bot.application.notice_delivery_ports import (
    DeliveryFailure,
    DeliveryReceipt,
    NoticeReceiptTransport,
)
from ugc_bot.application.ports import TransactionManager
from ugc_bot.domain.financial import utc

_LABELS = {
    "ru": (
        "Сводка по заказу",
        "Позиций",
        "Принято контактов",
        "Открыть сводку",
    ),
    "en": ("Order summary", "Positions", "Contacts accepted", "Open summary"),
    "kk": (
        "Тапсырыс қорытындысы",
        "Позициялар",
        "Қабылданған контактілер",
        "Қорытындыны ашу",
    ),
    "be": (
        "Зводка па заказе",
        "Пазіцый",
        "Прынята кантактаў",
        "Адкрыць зводку",
    ),
    "uz": (
        "Buyurtma xulosasi",
        "Pozitsiyalar",
        "Qabul qilingan kontaktlar",
        "Xulosani ochish",
    ),
}


def _render(source, urls):
    language = source.contact.locale.lower().split("-")[0].split("_")[0]
    locale = language if language in _LABELS else "ru"
    title, positions, contacts, label = _LABELS[locale]
    parsed = urlsplit(urls.get(source.contact.channel, ""))
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
        or parsed.port
        or any(c.isspace() or ord(c) < 32 for c in parsed.geturl())
        or any(
            k
            in {
                "summary",
                "assignment",
                "selection",
                "checkout",
                "campaign",
                "view",
            }
            for k, _ in parse_qsl(parsed.query, keep_blank_values=True)
        )
    ):
        raise ValueError("digest_launch_unavailable")
    query = parse_qsl(parsed.query, keep_blank_values=True)
    query.append(("summary", str(source.order_id)))
    url = urlunsplit(parsed._replace(query=urlencode(query)))
    summary = source.summary
    lines = [title, f"{positions}: {summary['total']}"]
    if summary["contact_accepted"] is not None:
        lines.append(f"{contacts}: {summary['contact_accepted']}")
    # Work/legacy counts live in the signed own-order screen. A notification
    # cannot relabel legacy feedback as paid work or expose private creators.
    return locale, "\n".join(lines), url, label


@dataclass
class CampaignDigestService:
    repository: CampaignDigestRepository
    transactions: TransactionManager
    transport: NoticeReceiptTransport
    clock: Clock
    launch_urls: dict[str, str]
    lease_seconds: int = 120

    def _now(self):
        return utc(self.clock.now())

    async def _source(self, request_id, session):
        order, recipient = await self.repository.scope(
            request_id, session=session
        )
        return await self.repository.lock_source(
            order, recipient, self._now(), session=session
        )

    async def _observe(
        self, request_id, attempt, kind, status, session, **values
    ):
        await self.repository.save_outcome(
            request_id,
            attempt.attempt_id if attempt else None,
            kind,
            status,
            self._now(),
            session=session,
            **values,
        )

    async def prepare(self, request_id):
        async with self.transactions.transaction() as session:
            source = await self._source(request_id, session)
            job = await self.repository.job(request_id, session=session)
            if job["state"] == "sending":
                if job["lease_until"] <= self._now():
                    old = await self.repository.attempt(
                        request_id, session=session
                    )
                    await self._observe(
                        request_id,
                        old,
                        "recovery",
                        "unknown",
                        session,
                        reason="digest_delivery_result_unknown",
                    )
                    await self.repository.save_job(
                        request_id, "unknown", session=session
                    )
                return None
            if job["state"] != "ready":
                return None
            try:
                if source is None:
                    raise ValueError("digest_scope_unavailable")
                locale, text, url, label = _render(source, self.launch_urls)
            except ValueError:
                await self._observe(
                    request_id,
                    None,
                    "preflight",
                    "obsolete",
                    session,
                    reason="digest_scope_or_launch_unavailable",
                )
                await self.repository.save_job(
                    request_id, "obsolete", session=session
                )
                return None
            now = self._now()
            attempt = DigestAttempt(
                uuid4(),
                request_id,
                uuid4(),
                now,
                now + timedelta(seconds=self.lease_seconds),
                canonical(source.summary),
                source.fingerprint,
                source.contact.channel,
                str(source.contact.address),
                source.contact.address_kind,
                locale,
                text,
                url,
                label,
            )
            await self.repository.save_attempt(attempt, session=session)
            await self.repository.save_job(
                request_id,
                "sending",
                session=session,
                attempt_id=attempt.attempt_id,
                lease_token=attempt.lease_token,
                lease_until=attempt.lease_until,
            )
            return attempt

    def _fenced(self, job, attempt):
        return (
            job["state"] == "sending"
            and job["attempt_id"] == attempt.attempt_id
            and job["lease_token"] == attempt.lease_token
            and job["lease_until"] == attempt.lease_until
            and job["lease_until"] > self._now()
        )

    async def deliver(self, attempt):
        async with self.transactions.transaction() as session:
            source = await self._source(attempt.request_id, session)
            job = await self.repository.job(attempt.request_id, session=session)
            stored = await self.repository.attempt(
                attempt.request_id, session=session
            )
            if stored != attempt:
                raise ValueError("digest_attempt_snapshot_invalid")
            if not self._fenced(job, attempt) or await self.repository.outcome(
                attempt.attempt_id, "started", session=session
            ):
                return
            if source is None or source.fingerprint != attempt.source_hash:
                await self._observe(
                    attempt.request_id,
                    attempt,
                    "preflight",
                    "obsolete",
                    session,
                    reason="digest_source_changed",
                )
                await self.repository.save_job(
                    attempt.request_id, "obsolete", session=session
                )
                return
            await self._observe(
                attempt.request_id, attempt, "started", "started", session
            )
        status, reference, reason = "unknown", None, None
        try:
            receipt = await self.transport.send(attempt)
            if (
                not isinstance(receipt, DeliveryReceipt)
                or receipt.channel != attempt.channel
                or not isinstance(receipt.reference, str)
                or not receipt.reference.strip()
            ):
                raise DeliveryFailure("digest_receipt_unknown", uncertain=True)
            status, reference = "accepted", receipt.reference
        except DeliveryFailure as exc:
            status = "unknown" if exc.uncertain else "failed"
            reason = "digest_transport_" + status
        except Exception:
            reason = "digest_transport_exception"
        async with self.transactions.transaction() as session:
            source = await self._source(attempt.request_id, session)
            job = await self.repository.job(attempt.request_id, session=session)
            current = (
                source is not None and source.fingerprint == attempt.source_hash
            )
            fenced = self._fenced(job, attempt)
            reused = (
                status == "accepted"
                and await self.repository.receipt_used(
                    attempt.channel, reference, session=session
                )
            )
            await self._observe(
                attempt.request_id,
                attempt,
                "transport",
                status,
                session,
                reference=reference,
                reason=reason
                or ("digest_provider_receipt_reused" if reused else None),
                applied=(
                    status == "accepted" and current and fenced and not reused
                ),
            )
            if fenced:
                await self.repository.save_job(
                    attempt.request_id,
                    ("unknown" if reused else status)
                    if current
                    else "obsolete",
                    session=session,
                )

    async def run_once(self, *, limit=100):
        if (
            type(limit) is not int
            or not 1 <= limit <= 1000
            or type(self.lease_seconds) is not int
            or self.lease_seconds < 1
        ):
            raise ValueError("digest_worker_bounds_invalid")
        async with self.transactions.transaction() as session:
            scopes = await self.repository.due_scopes(
                self._now(), limit, session=session
            )
        for order, recipient in scopes:
            async with self.transactions.transaction() as session:
                source = await self.repository.lock_source(
                    order, recipient, self._now(), session=session
                )
                if source is not None:
                    await self.repository.enqueue(
                        source, self._now(), session=session
                    )
        async with self.transactions.transaction() as session:
            requests = await self.repository.candidates(
                self._now(), limit, session=session
            )
        for request_id in requests:
            attempt = await self.prepare(request_id)
            if attempt is not None:
                await self.deliver(attempt)
        return len(requests)
