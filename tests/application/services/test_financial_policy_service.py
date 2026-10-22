from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from ugc_bot.config import AppConfig


def test_policy_fails_closed():
    config = AppConfig.model_validate({"BOT_TOKEN": "test"})
    assert getattr(config, "financial", None) is not None, (
        "Missing fail-closed financial configuration"
    )
    assert config.financial.core_enabled is False
    assert config.financial.new_orders_enabled is False
    assert config.financial.payouts_enabled is False
    from ugc_bot.application.services.financial_policy_service import (
        FinancialPolicyService,
    )

    with pytest.raises(ValueError, match="financial_disabled"):
        FinancialPolicyService(config.financial).validate_for_capture(
            policy=None,
            client_id=uuid4(),
            order_created_at=datetime.now(timezone.utc),
            financial_version=None,
            selection_due_at=None,
            currency="RUB",
            captured_at=datetime.now(timezone.utc),
        )


def ready_policy():
    from ugc_bot.application.services.financial_policy_service import (
        FinancialPolicy,
        FinancialPolicyService,
    )
    from ugc_bot.config import FinancialConfig

    client = uuid4()
    created = datetime(2026, 1, 2, tzinfo=timezone.utc)
    policy = FinancialPolicy(
        version="v1-test-policy",
        approved_by=uuid4(),
        approved_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        effective_from=datetime(2026, 1, 1, 12, tzinfo=timezone.utc),
        selection_refund_window=timedelta(days=7),
        allowed_clients=frozenset({client}),
        terms_reference="https://example.test/policy",
    )
    service = FinancialPolicyService(
        FinancialConfig(
            FINANCIAL_CORE_ENABLED=True, FINANCIAL_NEW_ORDERS_ENABLED=True
        )
    )
    args = dict(
        policy=policy,
        client_id=client,
        order_created_at=created,
        financial_version=policy.version,
        selection_due_at=created + timedelta(days=3),
        currency="RUB",
        captured_at=created + timedelta(hours=1),
    )
    return service, policy, args


def test_policy_requires_a_real_approver_identity():
    from dataclasses import replace

    service, policy, args = ready_policy()
    args["policy"] = replace(policy, approved_by="forged")
    with pytest.raises(ValueError, match="approved_policy"):
        service.validate_for_capture(**args)


def test_policy_requires_a_validated_client_uuid():
    from dataclasses import replace

    service, policy, args = ready_policy()
    args.update(
        client_id="forged",
        policy=replace(policy, allowed_clients=frozenset({"forged"})),
    )
    with pytest.raises(ValueError, match="client_identity"):
        service.validate_for_capture(**args)


def test_policy_allowlist_snapshot_is_not_mutable_through_original_container():
    from dataclasses import replace

    service, policy, args = ready_policy()
    original = set(policy.allowed_clients)
    args["policy"] = replace(policy, allowed_clients=original)
    rogue = uuid4()
    original.add(rogue)
    args["client_id"] = rogue
    with pytest.raises(ValueError, match="client_not_allowlisted"):
        service.validate_for_capture(**args)


def test_fully_approved_explicit_policy_allows_only_its_new_order():
    service, policy, args = ready_policy()
    assert service.validate_for_capture(**args) is policy


@pytest.mark.parametrize(
    "changes,error",
    [
        ({"policy": None}, "approved_policy"),
        ({"financial_version": None}, "approved_policy"),
        ({"financial_version": "other"}, "approved_policy"),
        ({"client_id": uuid4()}, "client_not_allowlisted"),
        ({"currency": "USD"}, "unpublished_currency"),
        ({"selection_due_at": None}, "agreed_selection_due_at"),
    ],
)
def test_capture_gate_never_fills_missing_inputs_with_defaults(changes, error):
    service, _, args = ready_policy()
    args.update(changes)
    with pytest.raises(ValueError, match=error):
        service.validate_for_capture(**args)


@pytest.mark.parametrize(
    "changes,error",
    [
        ({"approved_by": None}, "approved_policy"),
        ({"approved_at": None}, "approved_policy"),
        ({"effective_from": None}, "approved_policy"),
        ({"selection_refund_window": None}, "selection_refund_window"),
        ({"selection_refund_window": timedelta(0)}, "selection_refund_window"),
        (
            {"selection_refund_window": timedelta(days=-1)},
            "selection_refund_window",
        ),
        ({"terms_reference": None}, "published_terms"),
        ({"terms_reference": " "}, "published_terms"),
    ],
)
def test_approval_document_and_refund_window_are_real_required_inputs(
    changes, error
):
    from dataclasses import replace

    service, policy, args = ready_policy()
    args["policy"] = replace(policy, **changes)
    with pytest.raises(ValueError, match=error):
        service.validate_for_capture(**args)


def test_deadline_is_order_specific_and_pre_activation_orders_stay_legacy():
    service, policy, args = ready_policy()
    for change, error in [
        ({"selection_due_at": args["captured_at"]}, "agreed_selection_due_at"),
        (
            {"captured_at": args["order_created_at"] - timedelta(seconds=1)},
            "legacy_order_not_eligible",
        ),
        (
            {"order_created_at": policy.effective_from - timedelta(seconds=1)},
            "legacy_order_not_eligible",
        ),
    ]:
        with pytest.raises(ValueError, match=error):
            service.validate_for_capture(**(args | change))


@pytest.mark.parametrize(
    "flag", ["FINANCIAL_CORE_ENABLED", "FINANCIAL_NEW_ORDERS_ENABLED"]
)
def test_either_new_capture_emergency_gate_fails_closed(flag):
    from ugc_bot.application.services.financial_policy_service import (
        FinancialPolicyService,
    )
    from ugc_bot.config import FinancialConfig

    _, _, args = ready_policy()
    flags = dict(FINANCIAL_CORE_ENABLED=True, FINANCIAL_NEW_ORDERS_ENABLED=True)
    flags[flag] = False
    with pytest.raises(ValueError, match="financial_disabled"):
        FinancialPolicyService(FinancialConfig(**flags)).validate_for_capture(
            **args
        )


@pytest.mark.parametrize(
    "operation", ["create_override", "apply_override", "set_nonstandard_price"]
)
def test_no_future_override_policy_is_silently_enabled(operation):
    service, _, _ = ready_policy()
    with pytest.raises(ValueError, match="policy_feature_disabled"):
        getattr(service, operation)()


def test_flat_and_nested_financial_flags_agree_without_other_defaults():
    flags = dict(
        FINANCIAL_CORE_ENABLED=True,
        FINANCIAL_NEW_ORDERS_ENABLED=True,
        FINANCIAL_PAYOUTS_ENABLED=False,
    )
    flat = AppConfig.model_validate({"BOT_TOKEN": "test", **flags})
    sections = AppConfig.model_validate({"BOT_TOKEN": "test"}).model_dump()
    sections["financial"] = flags
    nested = AppConfig.model_validate(sections)
    assert flat.financial == nested.financial
    assert flat.financial.core_enabled is True
    assert flat.financial.new_orders_enabled is True
    assert flat.financial.payouts_enabled is False


def test_blank_policy_identity_is_not_a_publishable_version():
    from dataclasses import replace

    service, policy, args = ready_policy()
    args.update(policy=replace(policy, version=" "), financial_version=" ")
    with pytest.raises(ValueError, match="approved_policy"):
        service.validate_for_capture(**args)
