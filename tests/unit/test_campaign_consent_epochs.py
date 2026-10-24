"""A new relation cannot reactivate consent to an interrupted old relation."""

from datetime import datetime, timezone
from uuid import UUID

import pytest

from ugc_bot.domain.campaigns import digest

AT = datetime(2026, 10, 24, tzinfo=timezone.utc)
CREATOR, OWNER, OTHER = (UUID(int=n) for n in (1, 2, 3))


def binding(owner=OWNER):
    return {
        "referred_user_id": CREATOR,
        "referrer_user_id": owner,
        "created_at": AT,
    }


def observation(sequence, *, active=True, owner=OWNER):
    return {
        **binding(owner),
        "observation_sequence": sequence,
        "active": active,
    }


def context(sequences=(1,)):
    return {
        "actor": {
            "user_id": CREATOR,
            "status": "active",
            "telegram_usable": True,
        },
        "inviter": {"user_id": OWNER, "status": "active"},
        "canonical_identity": "real-ig-identity",
        "binding_created_at": AT,
        "binding_sequence": min(sequences),
        "binding_witness_sequences": sequences,
    }


def recorded_context(sequence):
    return digest(
        {
            "purpose": "umc:campaign-consent-context:v1",
            "actor_id": str(CREATOR),
            "owner_id": str(OWNER),
            "canonical_identity": "real-ig-identity",
            "binding_created_at": "2026-10-24T00:00:00+00:00",
            "binding_sequence": sequence,
        }
    )


def test_epoch_survives_identical_observations_but_not_an_interruption():
    from ugc_bot.application.services.campaign_consent import binding_epoch

    epoch = binding_epoch(binding(), [observation(3), observation(1)])
    assert epoch.sequence == 1 and epoch.witness_sequences == (1, 3)
    epoch = binding_epoch(
        binding(),
        [
            observation(9),
            observation(8, active=False),
            observation(7, owner=OTHER),
            observation(1),
        ],
    )
    assert epoch.sequence == 9 and epoch.witness_sequences == (9,)


@pytest.mark.parametrize(
    "rows", [[], [observation(1, active=False)], [observation(1, owner=OTHER)]]
)
def test_missing_or_mismatched_current_history_is_unavailable(rows):
    from ugc_bot.application.services.campaign_consent import binding_epoch

    with pytest.raises(ValueError, match="foundation_unavailable"):
        binding_epoch(binding(), rows)


def test_effective_consent_verifies_original_receipt_against_current_epoch():
    from ugc_bot.application.services.campaign_consent import (
        effective_consent_reason,
    )

    policy = {
        "enabled": True,
        "publication_version": 1,
        "terms_version": "v1",
        "terms_hash": "a" * 64,
    }
    consent = {
        "active": True,
        "actor_id": CREATOR,
        "creator_id": CREATOR,
        "owner_id": OWNER,
        "canonical_identity": "real-ig-identity",
        "binding_created_at": AT,
        "policy_version": 1,
        "terms_version": "v1",
        "terms_hash": "a" * 64,
        "operation_key": "actual-opt-in",
    }
    publisher = {"active": True}
    receipt = {
        "actor_id": CREATOR,
        "operation_key": "actual-opt-in",
        "action": "consent",
        "result": {"consent_context": recorded_context(3)},
    }
    assert (
        effective_consent_reason(
            context((1, 3)), policy, publisher, consent, receipt
        )
        is None
    )
    assert (
        effective_consent_reason(
            context((9,)), policy, publisher, consent, receipt
        )
        == "consent_binding_changed"
    )
    assert (
        effective_consent_reason(context(), policy, publisher, consent, None)
        == "consent_proof_unavailable"
    )
    consent["active"] = False
    assert (
        effective_consent_reason(context(), policy, publisher, consent, receipt)
        == "consent_absent"
    )


def test_context_uses_normalized_epoch_and_missing_identity_has_no_context():
    from ugc_bot.application.services.campaign_consent import consent_context

    ctx = context((1, 3))
    assert consent_context(ctx) == recorded_context(1)
    ctx["canonical_identity"] = None
    assert consent_context(ctx) is None


@pytest.mark.parametrize(
    "change,wanted",
    [
        ("creator_status", "account_inactive"),
        ("identity", "creator_unverified"),
        ("inviter", "inviter_missing"),
        ("self", "inviter_missing"),
        ("policy_missing", "policy_missing"),
        ("policy_suspended", "policy_suspended"),
        ("owner_status", "inviter_not_publisher"),
        ("grant", "inviter_not_publisher"),
        ("contact", "telegram_unavailable"),
    ],
)
def test_current_eligibility_is_authoritative_before_old_consent(
    change, wanted
):
    from ugc_bot.application.services.campaign_consent import consent_reason

    ctx, policy, publisher = context(), {"enabled": True}, {"active": True}
    if change == "creator_status":
        ctx["actor"]["status"] = "pause"
    elif change == "identity":
        ctx["canonical_identity"] = None
    elif change == "inviter":
        ctx["inviter"] = None
    elif change == "self":
        ctx["inviter"]["user_id"] = CREATOR
    elif change == "policy_missing":
        policy = None
    elif change == "policy_suspended":
        policy["enabled"] = False
    elif change == "owner_status":
        ctx["inviter"]["status"] = "blocked"
    elif change == "grant":
        publisher = None
    else:
        ctx["actor"]["telegram_usable"] = False
    assert consent_reason(ctx, policy, publisher) == wanted
