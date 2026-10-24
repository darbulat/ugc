"""Commit attempt, release DB connection, send once, then record result."""

import hashlib
from dataclasses import dataclass, replace
from datetime import timedelta
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from ugc_bot.application.accompaniment_lead_ports import (
    AccompanimentLeadDeliveryRepository,
    LeadAttempt,
    LeadOutcome,
    LeadReceiptTransport,
)
from ugc_bot.application.financial_ports import Clock
from ugc_bot.application.notice_delivery_ports import DeliveryFailure
from ugc_bot.application.ports import TransactionManager
from ugc_bot.domain.financial import utc


@dataclass
class AccompanimentLeadDelivery:
    repository: AccompanimentLeadDeliveryRepository
    transactions: TransactionManager
    transport: LeadReceiptTransport
    clock: Clock
    lease_seconds: int = 120

    def __post_init__(self) -> None:
        if type(self.lease_seconds) is not int or self.lease_seconds < 1:
            raise ValueError("lead_lease_invalid")

    async def prepare(self) -> LeadAttempt | None:
        repo, now = self.repository, utc(self.clock.now())
        async with self.transactions.transaction() as session:
            await repo.expand(now, 100, session=session)
            for job_id in await repo.candidates(now, 100, session=session):
                job = await repo.lock_job(job_id, session=session)
                if job is None:
                    continue
                if job.state == "sending":
                    if job.lease_until is None or job.lease_until > now:
                        continue
                    assert job.current_attempt_id is not None
                    await repo.save_outcome(
                        LeadOutcome(
                            uuid5(job.current_attempt_id, "recovery"),
                            job.current_attempt_id,
                            job.job_id,
                            job.lead_id,
                            job.order_id,
                            "recovery",
                            "unknown",
                            now,
                            reason="delivery_lease_expired",
                        ),
                        session=session,
                    )
                    await repo.save_job(
                        replace(job, state="unknown"), session=session
                    )
                    continue
                if job.state != "ready":
                    continue
                lead = await repo.lead(job.lead_id, session=session)
                contact = await repo.contact(job.recipient_id, session=session)
                if contact is None or not contact.address:
                    await repo.save_job(
                        replace(job, state="obsolete"), session=session
                    )
                    continue
                text = (
                    "Заявка на сопровождение UMC\n"
                    f"Заказ: {lead.order_id}\n"
                    f"Позиции: {', '.join(map(str, lead.selected_ordinals))}\n"
                    f"Контакт, указанный клиентом: {lead.contact_reference}\n\n"
                    "Заявка создана до оплаты. Это не подтверждение оплаты, "
                    "назначения менеджера или успешной работы.\n"
                    "Гонорар автору оплачивается напрямую; вознаграждение "
                    "менеджеру этим запросом не начисляется."
                )
                attempt = LeadAttempt(
                    uuid4(),
                    job.job_id,
                    job.lead_id,
                    job.order_id,
                    job.recipient_id,
                    job.attempt_count + 1,
                    uuid4(),
                    now,
                    now + timedelta(seconds=self.lease_seconds),
                    contact.channel,
                    contact.address,
                    contact.address_kind,
                    text,
                )
                await repo.save_attempt(attempt, session=session)
                await repo.save_job(
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
        return None

    async def finish(
        self,
        attempt: LeadAttempt,
        *,
        reference: str | None,
        failure: DeliveryFailure | None,
    ) -> None:
        repo, now = self.repository, utc(self.clock.now())
        async with self.transactions.transaction() as session:
            job = await repo.lock_job(attempt.job_id, session=session)
            if (
                job is None
                or await repo.get_attempt(attempt.attempt_id, session=session)
                != attempt
            ):
                raise ValueError("lead_attempt_source_mismatch")
            current = (
                job.state == "sending"
                and job.current_attempt_id == attempt.attempt_id
                and job.lease_token == attempt.lease_token
            )
            contact = await repo.contact(attempt.recipient_id, session=session)
            same_contact = contact is not None and (
                contact.channel,
                contact.address,
                contact.address_kind,
            ) == (attempt.channel, attempt.address, attempt.address_kind)
            applied = current and same_contact
            status = (
                "accepted"
                if failure is None
                else ("unknown" if failure.uncertain else "failed")
            )
            await repo.save_outcome(
                LeadOutcome(
                    uuid5(attempt.attempt_id, "result"),
                    attempt.attempt_id,
                    job.job_id,
                    job.lead_id,
                    job.order_id,
                    "result",
                    status,
                    now,
                    reference,
                    failure.code if failure else None,
                    applied,
                ),
                session=session,
            )
            if current:
                await repo.save_job(
                    replace(job, state=status if same_contact else "obsolete"),
                    session=session,
                )

    async def run_once(self, limit: int = 100) -> int:
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("lead_batch_invalid")
        attempted = 0
        for _ in range(limit):
            attempt = await self.prepare()
            if attempt is None:
                break
            failure, reference = None, None
            try:
                receipt = await self.transport.send(attempt)
                if (
                    receipt.channel != attempt.channel
                    or not receipt.reference.strip()
                ):
                    raise DeliveryFailure(
                        "lead_receipt_invalid", uncertain=True
                    )
                reference = receipt.reference
            except DeliveryFailure as exc:
                failure = exc
            except Exception:
                failure = DeliveryFailure("lead_result_unknown", uncertain=True)
            await self.finish(attempt, reference=reference, failure=failure)
            attempted += 1
        return attempted

    async def retry(
        self, job_id: UUID, *, actor_id: UUID, reason: str, operation_key: str
    ) -> None:
        if (
            not reason.strip()
            or len(reason) > 4000
            or not operation_key.strip()
            or len(operation_key) > 256
        ):
            raise ValueError("lead_retry_provenance_required")
        digest = hashlib.sha256(
            f"{job_id}:{actor_id}:{reason}".encode()
        ).hexdigest()
        repo = self.repository
        async with self.transactions.transaction() as session:
            job = await repo.lock_job(job_id, session=session)
            if not await repo.is_admin(actor_id, session=session):
                raise PermissionError("active_admin_required")
            previous = await repo.command_outcome(
                operation_key, session=session
            )
            if previous is not None:
                if previous.payload_hash != digest:
                    raise ValueError("idempotency_payload_conflict")
                return
            if job is None or job.state not in ("failed", "unknown"):
                raise ValueError("lead_retry_requires_failed_or_unknown")
            assert job.current_attempt_id is not None
            await repo.save_outcome(
                LeadOutcome(
                    uuid5(NAMESPACE_URL, "lead-retry:" + operation_key),
                    job.current_attempt_id,
                    job.job_id,
                    job.lead_id,
                    job.order_id,
                    "retry",
                    "ready",
                    utc(self.clock.now()),
                    reason=reason,
                    actor_id=actor_id,
                    operation_key=operation_key,
                    payload_hash=digest,
                ),
                session=session,
            )
            await repo.save_job(replace(job, state="ready"), session=session)
