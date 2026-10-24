"""Reject invented authority, incomplete terms and unconfigured quota inputs."""

from uuid import UUID, uuid4

import pytest

from tests.postgres_financial.test_campaign_foundation import policy_payload
from ugc_bot.domain.campaigns import CampaignCommand


@pytest.mark.parametrize(
    "change",
    [
        {"actor_id": UUID(int=0)},
        {"operation_key": " "},
        {"expected_version": True},
        {"expected_version": -1},
        {"action": "approve"},
        {"payload": {"is_admin": True}},
    ],
)
def test_command_requires_authenticated_identity_exact_action_and_version(
    change,
):
    args = dict(
        actor_id=uuid4(),
        operation_key="synthetic-operation",
        action="unsubscribe",
        expected_version=0,
        payload={},
    )
    with pytest.raises(ValueError):
        CampaignCommand(**{**args, **change})


@pytest.mark.parametrize(
    "field,value",
    [
        ("terms", {}),
        ("terms", {"ru": " "}),
        ("terms", {"de": "Not a supported locale"}),
        ("default_locale", "kk"),
        ("terms_version", " "),
        ("reason", ""),
        ("limits", {}),
        ("limits", {"recipients_per_campaign": True}),
    ],
)
def test_publication_requires_full_terms_and_every_explicit_limit(field, value):
    with pytest.raises(ValueError):
        CampaignCommand(
            uuid4(),
            "synthetic",
            "publish",
            0,
            {**policy_payload(), field: value},
        )


@pytest.mark.parametrize("bad", [True, 0, -1, 2147483648, "7"])
def test_quotas_are_required_positive_integers_without_implicit_coercion(bad):
    payload = policy_payload()
    payload["limits"]["recipients_per_campaign"] = bad
    with pytest.raises(ValueError, match="positive_limits"):
        CampaignCommand(uuid4(), "synthetic", "publish", 0, payload)


@pytest.mark.parametrize(
    "action,payload",
    [
        ("grant", {"owner_id": str(UUID(int=0)), "reason": "test"}),
        ("consent", {"policy_version": True, "terms_hash": "a" * 64}),
        ("consent", {"policy_version": 1, "terms_hash": "bad"}),
    ],
)
def test_actual_owner_and_exact_terms_reference_are_required(action, payload):
    with pytest.raises(ValueError):
        if action == "consent":
            payload = {**payload, "consent_context": "b" * 64}
        CampaignCommand(uuid4(), "synthetic", action, 0, payload)


@pytest.mark.parametrize("context", [None, "", "f" * 63, "f" * 65])
def test_consent_requires_original_settings_context(context):
    with pytest.raises(ValueError, match="terms_reference_required"):
        CampaignCommand(
            uuid4(),
            "synthetic-context",
            "consent",
            0,
            {
                "policy_version": 1,
                "terms_hash": "a" * 64,
                "consent_context": context,
            },
        )
