"""Current authority, immutable policy and creator-owned consent."""

from dataclasses import dataclass
from uuid import NAMESPACE_URL, UUID, uuid5

from ugc_bot.application.campaign_ports import CampaignRepository
from ugc_bot.application.financial_ports import Clock
from ugc_bot.application.services.campaign_consent import (
    consent_context,
    consent_reason,
    effective_consent_reason,
)
from ugc_bot.domain.campaigns import (
    CampaignCommand,
    CampaignConflict,
    publication,
)
from ugc_bot.domain.financial import utc

POLICY_FIELDS = (
    "publication_version",
    "terms_version",
    "terms_hash",
    "default_locale",
    "terms",
    "limits",
    "enabled",
)
CONSENT_FIELDS = (
    "owner_id",
    "canonical_identity",
    "binding_created_at",
    "policy_version",
    "terms_version",
    "terms_hash",
)


def active_admin(user):
    return bool(user and user["admin"] and user["status"] == "active")


def require_admin(user):
    if not active_admin(user):
        raise PermissionError("campaign_current_admin_required")


@dataclass
class CampaignFoundationService:
    repository: CampaignRepository
    clock: Clock

    async def view(self, actor_id: UUID, *, session: object):
        repo = self.repository
        at = await repo.begin_snapshot(session=session)
        ctx = await repo.context(actor_id, lock=False, session=session)
        policy = await repo.current("policy", session=session)
        own = await repo.current("publisher", actor_id, session=session)
        consent = await repo.current("consent", actor_id, session=session)
        inviter = ctx["inviter"]
        publisher = (
            await repo.current("publisher", inviter["user_id"], session=session)
            if inviter
            else None
        )
        reason = consent_reason(ctx, policy, publisher)
        proof = (
            await repo.receipt(
                consent["actor_id"], consent["operation_key"], session=session
            )
            if consent and consent["active"]
            else None
        )
        effective_reason = effective_consent_reason(
            ctx, policy, publisher, consent, proof
        )
        effective = effective_reason is None
        return {
            "actor_id": str(actor_id),
            "consent_context": consent_context(ctx),
            "as_of": utc(at).isoformat(),
            "can_admin": active_admin(ctx["actor"]),
            "policy": {
                k: policy[k] for k in (*POLICY_FIELDS, "version", "recorded_at")
            }
            if policy
            else None,
            "publisher": {
                "version": own["version"] if own else 0,
                "active": bool(
                    own and own["active"] and ctx["actor"]["status"] == "active"
                ),
            },
            "inviter": {"label": inviter["label"]} if inviter else None,
            "consent": {
                "version": consent["version"] if consent else 0,
                "active": bool(consent and consent["active"]),
                "effective": effective,
                "terms_version": consent["terms_version"] if consent else None,
            },
            "can_consent": reason is None and not effective,
            "consent_unavailable_reason": reason,
            "consent_effective_reason": effective_reason,
            "can_unsubscribe": bool(consent and consent["active"]),
            "delivery_state": "not_implemented",
        }

    async def accounts(
        self, actor_id: UUID, search: str, page: int, *, session: object
    ):
        if (
            not isinstance(search, str)
            or len(search) > 100
            or type(page) is not int
            or not 0 <= page <= 100000
        ):
            raise ValueError("campaign_invalid_page")
        at = await self.repository.begin_snapshot(session=session)
        ctx = await self.repository.context(
            actor_id, lock=False, session=session
        )
        require_admin(ctx["actor"])
        rows = await self.repository.accounts(search, page, session=session)
        return {
            "accounts": rows[:25],
            "has_more": len(rows) > 25,
            "page": page,
            "as_of": utc(at).isoformat(),
        }

    async def execute(self, command: CampaignCommand, *, session: object):
        if not isinstance(command, CampaignCommand):
            raise ValueError("typed_campaign_command_required")
        repo, action = self.repository, command.action
        target = (
            UUID(command.payload["owner_id"])
            if action in ("grant", "revoke")
            else None
        )
        ctx = await repo.context(
            command.actor_id, target, lock=True, session=session
        )
        if action in ("publish", "suspend", "grant", "revoke"):
            require_admin(ctx["actor"])
        stream, subject = self._stream(command, target)
        current = await repo.current(stream, subject, session=session)
        policy = await repo.current("policy", session=session)
        if action == "consent":
            await self._require_consent(command, ctx, policy, session)
        previous = await repo.receipt(
            command.actor_id, command.operation_key, session=session
        )
        if previous:
            if previous["payload_hash"] != command.payload_hash:
                raise CampaignConflict("campaign_operation_conflict")
            return {
                **previous["result"],
                "is_current": bool(
                    current
                    and current["version"] == previous["result"]["version"]
                ),
            }
        version = current["version"] if current else 0
        if command.expected_version != version:
            raise CampaignConflict("campaign_version_conflict")
        values = await self._values(
            command, ctx, current, policy, version + 1, session
        )
        at = utc(self.clock.now())
        receipt = str(
            uuid5(
                NAMESPACE_URL,
                f"ugc:campaign:{command.actor_id}:{command.operation_key}",
            )
        )
        result = {
            "receipt_id": receipt,
            "action": action,
            "version": version + 1,
            "recorded_at": at.isoformat(),
        }
        if action == "consent":
            result["consent_context"] = command.payload["consent_context"]
        await repo.save_receipt(
            {
                "actor_id": command.actor_id,
                "operation_key": command.operation_key,
                "action": action,
                "payload_hash": command.payload_hash,
                "recorded_at": at,
                "result": result,
            },
            session=session,
        )
        await repo.append(
            stream,
            {
                **values,
                "version": version + 1,
                "actor_id": command.actor_id,
                "operation_key": command.operation_key,
                "recorded_at": at,
            },
            session=session,
        )
        return {**result, "is_current": True}

    @staticmethod
    def _stream(command, target):
        if command.action in ("publish", "suspend"):
            return "policy", None
        if target:
            return "publisher", target
        return "consent", command.actor_id

    async def _require_consent(self, command, ctx, policy, session):
        if command.payload["consent_context"] != consent_context(ctx):
            raise CampaignConflict("campaign_consent_context_changed")
        inviter = ctx["inviter"]
        publisher = (
            await self.repository.current(
                "publisher", inviter["user_id"], session=session
            )
            if inviter
            else None
        )
        reason = consent_reason(ctx, policy, publisher)
        if reason:
            raise PermissionError("campaign_" + reason)
        if (
            command.payload["policy_version"] != policy["publication_version"]
            or command.payload["terms_hash"] != policy["terms_hash"]
        ):
            raise CampaignConflict("campaign_terms_changed")

    async def _values(self, command, ctx, current, policy, version, session):
        action, payload = command.action, command.payload
        if action == "publish":
            values = publication(payload)
            known = await self.repository.known_terms(
                values["terms_version"], session=session
            )
            if known is not None and known != values["terms_hash"]:
                raise CampaignConflict("campaign_terms_version_reused")
            return {**values, "publication_version": version, "enabled": True}
        if action == "suspend":
            if not policy:
                raise CampaignConflict("campaign_policy_missing")
            return {
                **{k: policy[k] for k in POLICY_FIELDS},
                "enabled": False,
                "reason": payload["reason"],
            }
        if action in ("grant", "revoke"):
            return self._publisher_values(action, payload, ctx, current, policy)
        if action == "unsubscribe":
            if not current:
                raise CampaignConflict("campaign_consent_absent")
            return {
                **{k: current[k] for k in CONSENT_FIELDS},
                "creator_id": command.actor_id,
                "active": False,
            }
        return {
            "creator_id": command.actor_id,
            "owner_id": ctx["inviter"]["user_id"],
            "canonical_identity": ctx["canonical_identity"],
            "binding_created_at": ctx["binding_created_at"],
            "policy_version": policy["publication_version"],
            "terms_version": policy["terms_version"],
            "terms_hash": policy["terms_hash"],
            "active": True,
        }

    @staticmethod
    def _publisher_values(action, payload, ctx, current, policy):
        if ctx["target"] is None:
            raise LookupError("campaign_owner_not_found")
        if action == "grant" and (
            ctx["target"]["status"] != "active" or policy is None
        ):
            raise CampaignConflict("campaign_active_owner_and_policy_required")
        if action == "revoke" and current is None:
            raise CampaignConflict("campaign_publisher_absent")
        return {
            "owner_id": ctx["target"]["user_id"],
            "active": action == "grant",
            "reason": payload["reason"],
            "policy_version": policy["publication_version"],
        }
