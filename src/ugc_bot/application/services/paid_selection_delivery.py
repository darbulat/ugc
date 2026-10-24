"""Committed attempt/start -> unlocked one-shot send -> fenced observation."""

import re
from dataclasses import asdict, dataclass, replace
from datetime import timedelta
from urllib.parse import urlsplit
from uuid import UUID, uuid4, uuid5

from ugc_bot.application.collaboration_ports import canonical
from ugc_bot.application.financial_ports import Clock
from ugc_bot.application.notice_delivery_ports import (
    DeliveryFailure,
    DeliveryReceipt,
    NoticeReceiptTransport,
)
from ugc_bot.application.paid_selection_delivery_ports import (
    PaidSelectionDeliveryRepository,
    SelectionDeliveryAttempt,
    SelectionDeliveryJob,
    SelectionDeliveryOutcome,
)
from ugc_bot.application.ports import TransactionManager
from ugc_bot.domain.financial import utc


def _safe(value, *, limit=200):
    if value is None:
        return ""
    if (
        not isinstance(value, str)
        or len(value) > limit
        or any(ord(c) < 32 or ord(c) == 127 for c in value)
    ):
        raise ValueError("selection_contact_render_invalid")
    return value.strip()


def _locale(value):
    language = (value or "ru").lower().split("-")[0].split("_")[0]
    return language if language in ("ru", "en", "kk", "be", "uz") else "ru"


def _message(source):
    url = _safe(source.instagram_url, limit=512)
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in ("instagram.com", "www.instagram.com")
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.port
        or not re.fullmatch(r"/[A-Za-z0-9._]{1,64}/?", parsed.path)
    ):
        raise ValueError("selection_instagram_url_invalid")
    contact = source.creator_contact
    labels = {
        "ru": ("Креатор подтвердил интерес", "Телефон"),
        "en": ("Creator confirmed interest", "Phone"),
        "kk": ("Креатор қызығушылық танытты", "Телефон"),
        "be": ("Крэатар пацвердзіў цікавасць", "Тэлефон"),
        "uz": ("Kreator qiziqishini tasdiqladi", "Telefon"),
    }
    title, phone_label = labels[_locale(source.contact.locale)]
    name = _safe(contact.get("username"))
    lines = [title, name, "Instagram: " + url]
    for key, label in (
        ("telegram", "Telegram"),
        ("phone", phone_label),
    ):
        value = _safe(contact.get(key))
        if value:
            lines.append(label + ": " + value)
    return "\n".join(line for line in lines if line)


def _reason(exc):
    value = str(exc)
    return (
        value
        if re.fullmatch(r"[a-z0-9_]{1,100}", value)
        else "selection_source_invalid"
    )


@dataclass
class PaidSelectionDelivery:
    repository: PaidSelectionDeliveryRepository
    transactions: TransactionManager
    transport: NoticeReceiptTransport
    clock: Clock
    lease_seconds: int = 120

    def _now(self):
        return utc(self.clock.now())

    async def _source(self, job_id, session):
        try:
            source = await self.repository.lock_source(
                job_id, self._now(), session=session
            )
            invalid = (
                source.invalid_reason if source else "selection_job_missing"
            )
            # Acquiring User/funding/history/item barriers can wait past due.
            # Reassess time after that wait, before the committed start marker.
            if source is not None and self._now() >= source.due_at:
                invalid = "selection_order_unavailable"
            return source, invalid
        except ValueError as exc:
            if str(exc) == "selection_scope_changed_retry_required":
                raise
            return None, _reason(exc)

    async def _observe(
        self, job, attempt, kind, status, reference, reason, applied, session
    ):
        identity = attempt.attempt_id if attempt else job.job_id
        outcome = SelectionDeliveryOutcome(
            uuid5(identity, kind),
            job.job_id,
            job.order_id,
            attempt.attempt_id if attempt else None,
            kind,
            status,
            self._now(),
            reference,
            reason,
            applied,
        )
        previous = await self.repository.outcome(
            outcome.outcome_id, session=session
        )
        if previous is not None:
            if (
                previous.status,
                previous.provider_reference,
                previous.reason,
                previous.applied,
            ) != (status, reference, reason, applied):
                raise ValueError("selection_outcome_conflict")
            return previous
        await self.repository.save_outcome(outcome, session=session)
        return outcome

    async def _recover(self, job, session):
        attempt = (
            await self.repository.attempt(
                job.current_attempt_id, session=session
            )
            if job.current_attempt_id
            else None
        )
        await self._observe(
            job,
            attempt,
            "recovery",
            "unknown",
            None,
            "selection_delivery_result_unknown",
            False,
            session,
        )
        await self.repository.save_job(
            replace(job, state="unknown"), session=session
        )

    async def prepare(self, job_id: UUID) -> SelectionDeliveryAttempt | None:
        if type(self.lease_seconds) is not int or self.lease_seconds < 1:
            raise ValueError("selection_delivery_lease_invalid")
        async with self.transactions.transaction() as session:
            source, invalid = await self._source(job_id, session)
            job = await self.repository.job(job_id, session=session)
            if job is None:
                return None
            if job.state == "sending":
                if job.lease_until is None or job.lease_until <= self._now():
                    await self._recover(job, session)
                return None
            if job.state != "ready":
                return None
            if source is not None and not invalid:
                try:
                    text = _message(source)
                except (ValueError, UnicodeError) as exc:
                    invalid = _reason(exc)
            if invalid:
                await self._observe(
                    job,
                    None,
                    "preflight",
                    "obsolete",
                    None,
                    invalid,
                    False,
                    session,
                )
                await self.repository.save_job(
                    replace(job, state="obsolete"), session=session
                )
                return None
            assert source is not None and source.contact is not None
            now, contact = self._now(), source.contact
            attempt = SelectionDeliveryAttempt(
                uuid4(),
                job.job_id,
                source.interest_id,
                source.order_id,
                canonical(asdict(source)),
                source.source_hash,
                job.attempt_count + 1,
                uuid4(),
                now,
                now + timedelta(seconds=self.lease_seconds),
                contact.channel,
                contact.address,
                contact.address_kind,
                _locale(contact.locale),
                text,
            )
            await self.repository.save_attempt(attempt, session=session)
            await self.repository.save_job(
                replace(
                    job,
                    state="sending",
                    attempt_count=attempt.number,
                    current_attempt_id=attempt.attempt_id,
                    lease_token=attempt.lease_token,
                    lease_until=attempt.lease_until,
                ),
                session=session,
            )
            return attempt

    @staticmethod
    def _fenced(job: SelectionDeliveryJob, attempt: SelectionDeliveryAttempt):
        return (
            job.current_attempt_id == attempt.attempt_id
            and job.lease_token == attempt.lease_token
            and job.state == "sending"
            and job.lease_until == attempt.lease_until
            and job.attempt_count == attempt.number
        )

    async def _begin(self, attempt):
        async with self.transactions.transaction() as session:
            stored = await self.repository.attempt(
                attempt.attempt_id, session=session
            )
            if stored != attempt:
                raise ValueError("selection_attempt_snapshot_invalid")
            source, invalid = await self._source(attempt.job_id, session)
            job = await self.repository.job(attempt.job_id, session=session)
            if job is None or not self._fenced(job, attempt):
                return False
            if job.lease_until <= self._now():
                await self._recover(job, session)
                return False
            if await self.repository.outcome(
                uuid5(attempt.attempt_id, "started"), session=session
            ):
                return False
            if (
                invalid
                or source is None
                or source.source_hash != attempt.source_hash
            ):
                await self._observe(
                    job,
                    attempt,
                    "preflight",
                    "obsolete",
                    None,
                    invalid or "selection_source_changed",
                    False,
                    session,
                )
                await self.repository.save_job(
                    replace(job, state="obsolete"), session=session
                )
                return False
            await self._observe(
                job, attempt, "started", "started", None, None, False, session
            )
        return True

    async def _send(self, attempt):
        try:
            receipt = await self.transport.send(attempt)
            if (
                not isinstance(receipt, DeliveryReceipt)
                or receipt.channel != attempt.channel
                or not isinstance(receipt.reference, str)
                or not receipt.reference.strip()
            ):
                raise DeliveryFailure(
                    "selection_receipt_unknown", uncertain=True
                )
            return "accepted", receipt.reference, None
        except DeliveryFailure as exc:
            return "unknown" if exc.uncertain else "failed", None, _reason(exc)
        except Exception:
            return "unknown", None, "selection_transport_exception"

    async def _finish(self, attempt, status, reference, reason):
        async with self.transactions.transaction() as session:
            try:
                source, invalid = await self._source(attempt.job_id, session)
            except ValueError as exc:
                if str(exc) != "selection_scope_changed_retry_required":
                    raise
                # Transport already ran. Retain its result under the held
                # scope without applying it or acquiring newly found users.
                source, invalid = None, str(exc)
            job = await self.repository.job(attempt.job_id, session=session)
            if job is None:
                raise ValueError("selection_job_missing")
            old = await self.repository.outcome(
                uuid5(attempt.attempt_id, "transport"), session=session
            )
            if old is not None:
                if old.status != status or old.provider_reference != reference:
                    raise ValueError("selection_outcome_conflict")
                return
            fenced = (
                self._fenced(job, attempt) and job.lease_until > self._now()
            )
            current = (
                source is not None
                and invalid is None
                and source.source_hash == attempt.source_hash
            )
            reused = (
                status == "accepted"
                and await self.repository.receipt_used(
                    attempt.channel, reference, session=session
                )
            )
            applied = status == "accepted" and fenced and current and not reused
            outcome = await self._observe(
                job,
                attempt,
                "transport",
                status,
                reference,
                reason
                or ("selection_provider_receipt_reused" if reused else None)
                or invalid
                or (None if current else "selection_source_changed")
                or (None if fenced else "selection_fence_stale"),
                applied,
                session,
            )
            if applied:
                assert source is not None
                await self.repository.accept(
                    attempt, source, outcome, session=session
                )
            if self._fenced(job, attempt):
                state = (
                    status
                    if status != "accepted" or applied
                    else "obsolete"
                    if not current or reused
                    else "unknown"
                )
                await self.repository.save_job(
                    replace(job, state=state), session=session
                )

    async def deliver(self, attempt: SelectionDeliveryAttempt) -> None:
        if await self._begin(attempt):
            status, reference, reason = await self._send(attempt)
            await self._finish(attempt, status, reference, reason)

    async def run_once(self, *, limit: int = 100) -> int:
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("selection_delivery_limit_invalid")
        async with self.transactions.transaction() as session:
            jobs = await self.repository.candidates(
                self._now(), limit, session=session
            )
        for job_id in jobs:
            attempt = await self.prepare(job_id)
            if attempt is not None:
                await self.deliver(attempt)
        return len(jobs)
