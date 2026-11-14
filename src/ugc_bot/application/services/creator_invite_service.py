"""Manual allocation and user-initiated disclosure in the order card."""

from dataclasses import dataclass, replace

from ugc_bot.application.financial_ports import Clock
from ugc_bot.application.native_principal_ports import require_current_principal
from ugc_bot.application.ports import TransactionManager
from ugc_bot.application.services.paid_selection_delivery import (
    PaidSelectionDelivery,
    _message,
)
from ugc_bot.application.services.paid_selection_interest import (
    PaidSelectionInterestService,
)
from ugc_bot.infrastructure.db.creator_invite_models import MANUAL_READY
from ugc_bot.infrastructure.db.models import UserModel
from ugc_bot.infrastructure.db.repositories.creator_invites import (
    contact_job_query,
    invitation,
)
from ugc_bot.infrastructure.db.repositories.financial_items import _session


@dataclass
class CreatorInviteService:
    selection: PaidSelectionInterestService
    delivery: PaidSelectionDelivery
    transactions: TransactionManager
    clock: Clock

    async def preview(self, identity, user_id):
        async with self.transactions.transaction() as session:
            db = _session(session)
            return await invitation(db, identity, self.clock.now(), user_id)

    async def accept(self, identity, user_id):
        row = await self.preview(identity, user_id)
        result = await self.selection.respond(
            row["order_id"], user_id, invite_id=identity
        )
        if result is None:
            raise ValueError("creator_invite_unavailable")
        return result

    async def card_contact(self, principal, assignment_id, transport):
        async with self.transactions.transaction() as session:
            db = _session(session)
            user = await db.get(UserModel, principal.user_id)
            require_current_principal(
                principal,
                principal.user_id,
                user.user_id if user else None,
                user.telegram_id if user else None,
                None,
            )
            query = contact_job_query(principal.user_id, assignment_id)
            job = (await db.execute(query)).one_or_none()
            if job is None:
                raise ValueError("creator_invite_contact_unavailable")
        if job.state in (MANUAL_READY, "sending"):
            attempt = await self.delivery.prepare(job.job_id, card_request=True)
            if (
                attempt is None
                or attempt.channel != "telegram"
                or attempt.address != principal.external_id
            ):
                raise ValueError("creator_invite_contact_unavailable")
            await self.delivery.deliver(attempt, transport=transport)
            async with self.transactions.transaction() as session:
                db = _session(session)
                current = (await db.execute(query)).one_or_none()
                if current is None or current.state != "accepted":
                    raise ValueError("creator_invite_contact_unavailable")
            return
        if job.state != "accepted":
            raise ValueError("creator_invite_contact_unavailable")
        async with self.transactions.transaction() as session:
            db = _session(session)
            source = await self.delivery.repository.lock_source(
                job.job_id, self.clock.now(), session=db
            )
            current = (await db.execute(query)).one_or_none()
            if (
                source is None
                or current is None
                or current.state != "accepted"
                or source.invalid_reason != "selection_already_delivered"
                or source.contact is None
                or source.contact.channel != "telegram"
                or source.contact.address != principal.external_id
            ):
                raise ValueError("creator_invite_contact_unavailable")
            attempt = await self.delivery.repository.attempt(
                current.current_attempt_id, session=db
            )
            message = replace(attempt, text=_message(source))
        await transport.send(message)
