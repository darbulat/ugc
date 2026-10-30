"""A new public policy must not rewrite pilot facts or invent refund rules."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from ugc_bot.public_policy_from_pilot import (
    PUBLIC_URL,
    PUBLIC_VERSION,
    SOURCE_SHA256,
    SOURCE_URL,
    SOURCE_VERSION,
    PublicationRequest,
    build_public_rules,
    parse_refund_rules,
)


def pilot():
    return SimpleNamespace(
        version=SOURCE_VERSION,
        approved_by=uuid4(),
        approved_at=datetime(2026, 10, 24, tzinfo=timezone.utc),
        effective_from=datetime(2026, 10, 24, tzinfo=timezone.utc),
        refund_window_seconds=604800,
        rules={
            "allowed_clients": [str(uuid4()), str(uuid4())],
            "terms_reference": SOURCE_URL,
            "terms_sha256": SOURCE_SHA256,
            "approval_scope": "owner_product_rules_and_two_account_pilot_only",
            "financial_activation_authorized": False,
            "source_request_channel": "telegram",
            "source_approver_telegram_id": "1",
            "legal_accounting_signoff": "not_attested",
            "selection_minor": 50000,
            "accompaniment_minor": 120000,
            "currency": "RUB",
            "hold_seconds": 1209600,
            "selection_refund_window_anchor": "per_item_delivery_accepted_at",
            "creator_tiers": [{"rate_bps": 1000}],
        },
    )


def request(**kwargs):
    args = dict(
        version=PUBLIC_VERSION,
        actor_id=uuid4(),
        effective_from=datetime.now(timezone.utc) + timedelta(minutes=2),
        terms_url=PUBLIC_URL,
        terms_sha256="a" * 64,
        approval_reference="owner-confirmed-request:2026-10-30",
        refund_rules=parse_refund_rules(
            '{"schema_version":1,"selection_refund_window_seconds":604800,'
            '"selection_refund_window_anchor":"item_delivered",'
            '"selection_closure_mode":"manual",'
            '"accompaniment_refund_rates_bps":{},'
            '"accompaniment_manager_refund_mode":"manual_review"}'
        ),
    )
    return PublicationRequest(**(args | kwargs))


def test_public_policy_preserves_rules_without_inventing_refund_rules():
    source = pilot()
    original = deepcopy(source.rules)
    result = build_public_rules(source, request())
    assert source.rules == original
    assert result["allowed_clients"] == []
    assert result["all_clients"] is True
    assert result["terms_reference"] == PUBLIC_URL
    assert result["terms_sha256"] == "a" * 64
    assert result["approval_reference"] == "owner-confirmed-request:2026-10-30"
    assert result["source_policy_version"] == SOURCE_VERSION
    assert result["selection_minor"] == 50000
    assert result["accompaniment_minor"] == 120000
    assert result["creator_tiers"] == original["creator_tiers"]
    assert result["legal_accounting_signoff"] == "not_attested"
    assert result["refund_rules"] == request().refund_rules.to_document()
    assert "source_approver_telegram_id" not in result
    assert "source_request_channel" not in result


@pytest.mark.parametrize(
    "field,value",
    [
        ("selection_minor", 60000),
        ("accompaniment_minor", 170000),
        ("currency", "KZT"),
        ("selection_refund_window_anchor", "order_closed"),
        ("hold_seconds", 1),
        ("terms_reference", "https://example.test/other"),
    ],
)
def test_rejects_unexpected_pilot_terms(field, value):
    source = pilot()
    source.rules[field] = value
    with pytest.raises(ValueError, match="source_policy_mismatch"):
        build_public_rules(source, request())


@pytest.mark.parametrize(
    "change",
    [
        {"version": "other"},
        {"actor_id": None},
        {"approval_reference": ""},
        {"terms_url": "https://example.test/not-the-policy"},
        {"terms_sha256": "bad"},
        {"refund_rules": None},
    ],
)
def test_requires_auditable_explicit_publication_request(change):
    with pytest.raises(ValueError):
        build_public_rules(pilot(), request(**change))


def test_terms_checks_actual_local_and_public_bytes(tmp_path, monkeypatch):
    import hashlib
    from io import BytesIO

    from ugc_bot import public_policy_from_pilot as module

    local = tmp_path / "terms.html"
    local.write_bytes(b"known public conditions")
    digest = hashlib.sha256(local.read_bytes()).hexdigest()

    class Response(BytesIO):
        status = 200
        url = module.PUBLIC_URL

    monkeypatch.setattr(
        module,
        "urlopen",
        lambda *_args, **_kwargs: Response(local.read_bytes()),
    )
    module.checked_terms(local, digest, published=True)
    monkeypatch.setattr(
        module, "urlopen", lambda *_args, **_kwargs: Response(b"modified")
    )
    with pytest.raises(ValueError, match="public_terms_hash_mismatch"):
        module.checked_terms(local, digest, published=True)
    with pytest.raises(ValueError, match="local_terms_hash_mismatch"):
        module.checked_terms(local, "b" * 64, published=False)


@pytest.mark.parametrize(
    "raw",
    [
        "{}",
        '{"schema_version":1,"schema_version":1}',
        '{"schema_version":1,"selection_refund_window_seconds":7,'
        '"selection_refund_window_anchor":"item_delivered",'
        '"selection_closure_mode":"manual",'
        '"accompaniment_refund_rates_bps":{},'
        '"accompaniment_manager_refund_mode":"manual_review"}',
        '{"schema_version":1,"selection_refund_window_seconds":604800,'
        '"selection_refund_window_anchor":"order_closed",'
        '"selection_closure_mode":"manual",'
        '"accompaniment_refund_rates_bps":{},'
        '"accompaniment_manager_refund_mode":"manual_review"}',
    ],
)
def test_refund_rules_require_explicit_complete_matching_document(raw):
    with pytest.raises(ValueError):
        parse_refund_rules(raw)
