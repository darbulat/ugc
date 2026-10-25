"""Current-admin lead review and audited technical referral corrections."""

from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.application.partner_admin_ports import (
    BindingCorrectionCommand,
    LeadReviewCommand,
    PartnerAdminRepository,
    command_hash,
)
from ugc_bot.application.services.rate_override_service import (
    RateOverrideService,
)
from ugc_bot.domain.financial import utc


class PartnerAdminService:
    def __init__(self, repository: PartnerAdminRepository, clock):
        self.repository, self.clock = repository, clock

    async def _authority(self, actor_id, ids, principal, session):
        if not isinstance(principal, AuthenticatedMessengerPrincipal):
            raise ValueError("financial_principal_changed")
        users = await self.repository.lock_users(
            tuple(sorted({actor_id, *ids}, key=str)), session=session
        )
        RateOverrideService._require_admin(
            users.get(actor_id), actor_id, principal
        )
        return users

    async def context(self, actor_id, *, principal, session):
        await self._authority(actor_id, (), principal, session)
        return {
            "actor_id": str(actor_id),
            "server_time": utc(self.clock.now()),
            "capabilities": {"review_leads": True, "correct_binding": True},
        }

    async def queue(
        self, actor_id, *, principal, page=0, status="pending", session
    ):
        await self._authority(actor_id, (), principal, session)
        if (
            type(page) is not int
            or not 0 <= page <= 100000
            or status not in ("pending", "accepted", "rejected", "all")
        ):
            raise ValueError("lead_queue_invalid")
        return await self.repository.queue_leads(page, status, session=session)

    async def _replay(self, command, session):
        previous = await self.repository.command(
            command.operation_key, session=session
        )
        if previous is None:
            return None
        if previous[0] != command_hash(command):
            raise ValueError("idempotency_payload_conflict")
        return previous[1]

    async def review_lead(
        self, command: LeadReviewCommand, *, principal, session
    ):
        users = await self._authority(
            command.actor_id, command.manager_ids, principal, session
        )
        lead = await self.repository.lead_for_update(
            command.lead_id, session=session
        )
        previous = await self._replay(command, session)
        if previous is not None:
            return previous
        for manager_id in command.manager_ids:
            if manager_id not in users or users[manager_id].status != "active":
                raise ValueError("active_manager_required")
        if lead is None:
            raise ValueError("lead_not_found")
        if lead["version"] != command.expected_version:
            raise ValueError("lead_version_conflict")
        if lead["version"]:
            raise ValueError("lead_already_reviewed")
        at = utc(self.clock.now())
        result = {
            "operation_key": command.operation_key,
            "lead_id": str(command.lead_id),
            "order_id": str(lead["order_id"]),
            "version": 1,
            "state": "accepted" if command.action == "accept" else "rejected",
            "source_state": "requested_unpaid",
            "actor_id": str(command.actor_id),
            "reason": command.reason,
            "reviewed_at": at.isoformat(),
            "manager_ids": [str(uid) for uid in command.manager_ids],
        }
        await self.repository.save_lead_review(
            command, result, command_hash(command), at, session=session
        )
        return result

    async def correct_binding(
        self, command: BindingCorrectionCommand, *, principal, session
    ):
        users = await self._authority(
            command.actor_id,
            (
                command.referred_id,
                command.expected_referrer_id,
                command.referrer_id,
            ),
            principal,
            session,
        )
        if command.referred_id == command.referrer_id:
            raise ValueError("self_referral_forbidden")
        binding = await self.repository.binding_for_update(
            command.referred_id, session=session
        )
        previous = await self._replay(command, session)
        if previous is not None:
            return previous
        if command.referred_id not in users or command.referrer_id not in users:
            raise ValueError("referral_user_not_found")
        if users[command.referrer_id].status != "active":
            raise ValueError("active_referrer_required")
        if binding != command.expected_referrer_id:
            raise ValueError("referral_binding_changed")
        if binding == command.referrer_id:
            raise ValueError("referral_binding_unchanged")
        at = utc(self.clock.now())
        result = {
            "operation_key": command.operation_key,
            "referred_id": str(command.referred_id),
            "previous_referrer_id": str(binding),
            "referrer_id": str(command.referrer_id),
            "actor_id": str(command.actor_id),
            "reason": command.reason,
            "corrected_at": at.isoformat(),
        }
        await self.repository.save_binding_correction(
            command, result, command_hash(command), at, session=session
        )
        return result
