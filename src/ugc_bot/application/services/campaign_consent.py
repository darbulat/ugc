"""One authoritative current campaign-purpose consent predicate."""

from dataclasses import dataclass

from ugc_bot.domain.campaigns import digest
from ugc_bot.domain.financial import utc


@dataclass(frozen=True, slots=True)
class BindingEpoch:
    sequence: int
    witness_sequences: tuple[int, ...]


def binding_epoch(binding, observations) -> BindingEpoch:
    """Identical active witnesses stay in one uninterrupted relation epoch."""
    witnesses = []
    for row in sorted(
        observations,
        key=lambda value: value["observation_sequence"],
        reverse=True,
    ):
        same = row["active"] and all(
            row[key] == binding[key]
            for key in ("referred_user_id", "referrer_user_id", "created_at")
        )
        if not same:
            break
        witnesses.append(row["observation_sequence"])
    if not witnesses:
        raise ValueError("campaign_foundation_unavailable")
    return BindingEpoch(min(witnesses), tuple(sorted(witnesses)))


def consent_context(ctx, *, sequence=None):
    """Bind intent to actor, exact identity and normalized binding epoch."""
    if (
        ctx["inviter"] is None
        or not ctx["canonical_identity"]
        or ctx["binding_sequence"] is None
    ):
        return None
    return digest(
        {
            "purpose": "umc:campaign-consent-context:v1",
            "actor_id": str(ctx["actor"]["user_id"]),
            "owner_id": str(ctx["inviter"]["user_id"]),
            "canonical_identity": ctx["canonical_identity"],
            "binding_created_at": utc(ctx["binding_created_at"]).isoformat(),
            "binding_sequence": sequence
            if sequence is not None
            else ctx["binding_sequence"],
        }
    )


def consent_reason(context, policy, publisher):
    creator, owner = context["actor"], context["inviter"]
    if creator["status"] != "active":
        return "account_inactive"
    if not context["canonical_identity"]:
        return "creator_unverified"
    if owner is None or owner["user_id"] == creator["user_id"]:
        return "inviter_missing"
    if policy is None:
        return "policy_missing"
    if not policy["enabled"]:
        return "policy_suspended"
    if owner["status"] != "active" or not publisher or not publisher["active"]:
        return "inviter_not_publisher"
    if not creator["telegram_usable"]:
        return "telegram_unavailable"
    return None


def effective_consent_reason(ctx, policy, publisher, consent, receipt):
    reason = consent_reason(ctx, policy, publisher)
    if reason:
        return reason
    if not consent or not consent["active"]:
        return "consent_absent"
    creator = ctx["actor"]["user_id"]
    if (
        consent["actor_id"] != creator
        or consent["creator_id"] != creator
        or consent["owner_id"] != ctx["inviter"]["user_id"]
        or consent["canonical_identity"] != ctx["canonical_identity"]
        or consent["binding_created_at"] != ctx["binding_created_at"]
    ):
        return "consent_binding_changed"
    if any(
        consent[key] != policy[target]
        for key, target in (
            ("policy_version", "publication_version"),
            ("terms_version", "terms_version"),
            ("terms_hash", "terms_hash"),
        )
    ):
        return "consent_terms_changed"
    if (
        not receipt
        or receipt["actor_id"] != creator
        or receipt["operation_key"] != consent["operation_key"]
        or receipt["action"] != "consent"
        or not receipt["result"].get("consent_context")
    ):
        return "consent_proof_unavailable"
    proof = receipt["result"]["consent_context"]
    if not any(
        proof == consent_context(ctx, sequence=sequence)
        for sequence in ctx["binding_witness_sequences"]
    ):
        return "consent_binding_changed"
    return None
