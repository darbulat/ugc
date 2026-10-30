"""Publish environment choices as immutable policy facts."""

import importlib
import importlib.util
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from ugc_bot.application.services.financial_policy_service import (
    FinancialPolicy,
)
from ugc_bot.config import FinancialConfig

NOW = datetime(2026, 10, 25, tzinfo=timezone.utc)


def classes():
    name = "ugc_bot.application.services.financial_policy_publication"
    assert importlib.util.find_spec(name) is not None, (
        "Environment-backed policy publication is missing"
    )
    module = importlib.import_module(name)
    return module.FinancialPolicyDraft, module.FinancialPolicyPublicationService


def config(**changes):
    return FinancialConfig(
        **(
            {
                "FINANCIAL_SELECTION_PRICE_MINOR": 50000,
                "FINANCIAL_ACCOMPANIMENT_PRICE_MINOR": 120000,
                "FINANCIAL_SELECTION_REFUND_WINDOW_SECONDS": 604800,
                "FINANCIAL_SELECTION_REFUND_WINDOW_ANCHOR": "order_closed",
                "FINANCIAL_SELECTION_CLOSURE_MODE": "all_positions_resolved",
                "FINANCIAL_ACCOMPANIMENT_REFUND_RATES_BPS": {
                    "assigned": 10000,
                    "in_progress": 5000,
                    "success_final": 0,
                },
                "FINANCIAL_ACCOMPANIMENT_MANAGER_REFUND_MODE": "manual_review",
            }
            | changes
        )
    )


class Repository:
    def __init__(self):
        self.admin = True
        self.saved = {}
        self.calls = []

    async def lock_active_admin(self, actor_id, *, session):
        self.calls.append("admin")
        return self.admin

    async def lock_version(self, version, *, session):
        self.calls.append("version")

    async def load(self, version, *, session):
        self.calls.append("load")
        return self.saved.get(version)

    async def save_approved(self, policy, *, session):
        self.calls.append("save")
        assert policy.version not in self.saved
        self.saved[policy.version] = policy


class Transactions:
    @asynccontextmanager
    async def transaction(self):
        yield object()


class Clock:
    def now(self):
        return NOW


def inputs():
    return {
        "version": "refund-rules-test-v1",
        "effective_from": NOW + timedelta(days=1),
        "allowed_clients": frozenset({uuid4()}),
        "terms_reference": "terms:refunds:test:v1",
    }


def test_publication_requires_complete_environment_without_invented_terms():
    draft, _ = classes()
    with pytest.raises(ValueError, match="refund_rules_required"):
        draft.from_environment(FinancialConfig(), **inputs())


def test_draft_is_a_snapshot_and_does_not_create_approval():
    draft, _ = classes()
    cfg = config()
    chosen = draft.from_environment(cfg, **inputs())
    cfg.selection_refund_window_seconds = 86400
    document = chosen.to_document()
    assert document["refund_window_seconds"] == 604800
    assert document["refund_rules"]["selection_refund_window_anchor"] == (
        "order_closed"
    )
    assert "approved_by" not in document and "approved_at" not in document


@pytest.mark.asyncio
async def test_publication_preserves_rules_without_enabling_gates():
    draft, publisher = classes()
    cfg, repo, actor = config(), Repository(), uuid4()
    chosen = draft.from_environment(cfg, **inputs())
    service = publisher(repo, Transactions(), Clock())
    result = await service.publish(chosen, actor_id=actor)
    assert isinstance(result, FinancialPolicy)
    assert result.approved_by == actor and result.approved_at == NOW
    assert result.refund_rules == chosen.refund_rules
    assert result.selection_refund_window == timedelta(days=7)
    assert repo.calls == ["admin", "version", "load", "save"]
    assert not cfg.core_enabled and not cfg.new_orders_enabled


@pytest.mark.asyncio
async def test_replay_uses_original_approval_and_rechecks_current_admin():
    draft, publisher = classes()
    repo, actor = Repository(), uuid4()
    chosen = draft.from_environment(config(), **inputs())
    service = publisher(repo, Transactions(), Clock())
    result = await service.publish(chosen, actor_id=actor)
    assert await service.publish(chosen, actor_id=actor) is result
    assert repo.calls.count("save") == 1
    repo.admin = False
    with pytest.raises(PermissionError, match="active_admin_required"):
        await service.publish(chosen, actor_id=actor)
    assert repo.calls[-1] == "admin"


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["terms", "rules", "clients", "actor"])
async def test_existing_version_cannot_be_republished_with_changed_facts(
    change,
):
    draft, publisher = classes()
    repo, actor = Repository(), uuid4()
    chosen = draft.from_environment(config(), **inputs())
    service = publisher(repo, Transactions(), Clock())
    original = await service.publish(chosen, actor_id=actor)
    if change == "terms":
        chosen = replace(chosen, terms_reference="terms:changed")
    elif change == "clients":
        chosen = replace(chosen, allowed_clients=frozenset({uuid4()}))
    elif change == "rules":
        chosen = replace(
            chosen,
            refund_rules=replace(
                chosen.refund_rules, selection_refund_window_seconds=86400
            ),
        )
    else:
        actor = uuid4()
    with pytest.raises(ValueError, match="policy_version_conflict"):
        await service.publish(chosen, actor_id=actor)
    assert repo.saved[original.version] is original


@pytest.mark.asyncio
async def test_new_approval_cannot_be_backdated():
    draft, publisher = classes()
    chosen = draft.from_environment(
        config(), **(inputs() | {"effective_from": NOW - timedelta(days=1)})
    )
    repo = Repository()
    with pytest.raises(ValueError, match="approval_after_activation"):
        await publisher(repo, Transactions(), Clock()).publish(
            chosen, actor_id=uuid4()
        )
    assert not repo.saved


@pytest.mark.parametrize(
    "change",
    [
        {"version": " "},
        {"version": "x" * 65},
        {"effective_from": NOW.replace(tzinfo=None)},
        {"terms_reference": " "},
        {"allowed_clients": frozenset()},
        {"allowed_clients": frozenset({"forged"})},
    ],
)
def test_invalid_draft_cannot_reach_database(change):
    draft, _ = classes()
    with pytest.raises(ValueError):
        draft.from_environment(config(), **(inputs() | change))


@pytest.mark.asyncio
@pytest.mark.parametrize("actor", [None, "forged", UUID(int=0)])
async def test_invalid_actor_is_rejected_before_repository(actor):
    draft, publisher = classes()
    repo = Repository()
    chosen = draft.from_environment(config(), **inputs())
    with pytest.raises(PermissionError, match="active_admin_required"):
        await publisher(repo, Transactions(), Clock()).publish(
            chosen, actor_id=actor
        )
    assert repo.calls == []


@pytest.mark.asyncio
async def test_untyped_publication_draft_is_rejected_before_repository():
    _, publisher = classes()
    repo = Repository()
    with pytest.raises(ValueError, match="policy_draft_required"):
        await publisher(repo, Transactions(), Clock()).publish(
            {"version": "forged"}, actor_id=uuid4()
        )
    assert repo.calls == []


def test_draft_requires_typed_refund_rules():
    draft, _ = classes()
    chosen = draft.from_environment(config(), **inputs())
    with pytest.raises(ValueError, match="refund_rules_required"):
        replace(chosen, refund_rules=None)
