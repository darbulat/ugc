"""The maturity mode is a published policy fact, never a global toggle."""

import json
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from tests.application.services.test_financial_policy_service import (
    ready_policy,
)
from tests.application.services.test_public_policy_from_pilot import (
    pilot,
    request,
)
from tests.application.services.test_refund_policy_publication import (
    Clock,
    Repository,
    Transactions,
    classes,
    config,
    inputs,
)
from ugc_bot.infrastructure.db.repositories.financial_policy import (
    decode_policy_version,
)
from ugc_bot.public_policy_from_pilot import build_public_rules


def test_missing_mode_decodes_as_legacy_and_per_item_is_explicit():
    _, policy, args = ready_policy()
    row = SimpleNamespace(
        version=policy.version,
        approved_by=policy.approved_by,
        approved_at=policy.approved_at,
        effective_from=policy.effective_from,
        refund_window_seconds=604800,
        rules={
            "allowed_clients": [str(args["client_id"])],
            "terms_reference": policy.terms_reference,
        },
    )
    assert decode_policy_version(row).maturity_mode == "legacy"
    row.rules["maturity_mode"] = "per_item_v1"
    row.rules["selection_refund_window_anchor"] = (
        "per_item_delivery_accepted_at"
    )
    row.rules["hold_seconds"] = 1209600
    assert decode_policy_version(row).maturity_mode == "per_item_v1"
    row.rules["hold_seconds"] = 1
    with pytest.raises(ValueError, match="invalid_policy_document"):
        decode_policy_version(row)


@pytest.mark.parametrize("invalid", [None, True, "", "per_item", 1, [], {}])
def test_unrecognized_or_untyped_modes_are_rejected(invalid):
    _, policy, args = ready_policy()
    with pytest.raises(ValueError):
        replace(policy, maturity_mode=invalid)
    row = SimpleNamespace(
        version=policy.version,
        approved_by=policy.approved_by,
        approved_at=policy.approved_at,
        effective_from=policy.effective_from,
        refund_window_seconds=604800,
        rules={
            "allowed_clients": [str(args["client_id"])],
            "terms_reference": policy.terms_reference,
            "maturity_mode": invalid,
        },
    )
    with pytest.raises(ValueError, match="invalid_policy_document"):
        decode_policy_version(row)


def test_per_item_mode_refuses_a_different_window_or_anchor():
    _, policy, _ = ready_policy()
    with pytest.raises(ValueError, match="invalid_maturity_policy"):
        replace(
            policy,
            maturity_mode="per_item_v1",
            selection_refund_window=timedelta(days=3),
        )
    draft, _ = classes()
    with pytest.raises(ValueError, match="invalid_maturity_policy"):
        draft.from_environment(
            config(), **(inputs() | {"maturity_mode": "per_item_v1"})
        )


@pytest.mark.asyncio
async def test_published_maturity_mode_cannot_be_changed_by_retry():
    draft, publisher = classes()
    repo, actor = Repository(), uuid4()
    options = inputs() | {"maturity_mode": "per_item_v1"}
    chosen = draft.from_environment(
        config(FINANCIAL_SELECTION_REFUND_WINDOW_ANCHOR="item_delivered"),
        **options,
    )
    service = publisher(repo, Transactions(), Clock())
    public = await service.publish(chosen, actor_id=actor)
    assert public.maturity_mode == "per_item_v1"
    assert chosen.to_document()["maturity_mode"] == "per_item_v1"
    assert await service.publish(chosen, actor_id=actor) == public
    with pytest.raises(ValueError, match="policy_version_conflict"):
        await service.publish(
            replace(chosen, maturity_mode="legacy"), actor_id=actor
        )


def test_pilot_derived_policy_selects_per_item_and_only_supplied_rules():
    source = pilot()
    source.rules["hold_seconds"] = 1209600
    source.rules["selection_refund_window_anchor"] = (
        "per_item_delivery_accepted_at"
    )
    publication = request()
    rules = build_public_rules(source, publication)
    assert rules["maturity_mode"] == "per_item_v1"
    assert rules["refund_rules"] == publication.refund_rules.to_document()
    assert "refund_rules" not in source.rules
    assert "maturity_mode" not in source.rules


def test_standard_cli_explicitly_publishes_mode(monkeypatch, capsys):
    from tests.unit.test_financial_policy_config import arguments, module

    command = module()
    cfg = config(FINANCIAL_SELECTION_REFUND_WINDOW_ANCHOR="item_delivered")
    monkeypatch.setattr(
        command, "load_config", lambda: SimpleNamespace(financial=cfg)
    )
    assert command.main(arguments() + ["--maturity-mode", "per_item_v1"]) == 0
    assert json.loads(capsys.readouterr().out)["maturity_mode"] == "per_item_v1"
