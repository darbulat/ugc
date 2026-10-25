"""Operational admin review does not invent payment or success."""

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID

import pytest

from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.application.override_ports import OverrideUser
from ugc_bot.application.partner_admin_ports import (
    BindingCorrectionCommand,
    LeadReviewCommand,
)
from ugc_bot.application.services.partner_admin_service import (
    PartnerAdminService,
)

NOW = datetime(2026, 10, 25, tzinfo=timezone.utc)
ADMIN, CLIENT, MANAGER, OLD, NEW, LEAD = [UUID(int=i) for i in range(1, 7)]
PRINCIPAL = AuthenticatedMessengerPrincipal(ADMIN, "telegram", "admin-native")


class Repository:
    def __init__(self):
        self.users = {
            uid: OverrideUser(
                uid,
                "active",
                uid == ADMIN,
                "admin-native" if uid == ADMIN else str(uid),
            )
            for uid in (ADMIN, CLIENT, MANAGER, OLD, NEW)
        }
        self.lead = {
            "lead_id": LEAD,
            "order_id": UUID(int=90),
            "client_id": CLIENT,
            "version": 0,
            "source_state": "requested_unpaid",
        }
        self.commands = {}
        self.memberships = set()
        self.binding = OLD
        self.audits = []

    async def lock_users(self, ids, *, session):
        return {key: self.users[key] for key in ids if key in self.users}

    async def command(self, key, *, session):
        return self.commands.get(key)

    async def lead_for_update(self, lead_id, *, session):
        return self.lead if lead_id == LEAD else None

    async def save_lead_review(self, command, result, digest, at, *, session):
        self.lead["version"] = result["version"]
        self.memberships.update(command.manager_ids)
        self.commands[command.operation_key] = (digest, result)

    async def binding_for_update(self, referred_id, *, session):
        return self.binding

    async def save_binding_correction(
        self, command, result, digest, at, *, session
    ):
        self.binding = command.referrer_id
        self.audits.append(
            (
                command.actor_id,
                command.reason,
                command.expected_referrer_id,
                command.referrer_id,
            )
        )
        self.commands[command.operation_key] = (digest, result)


def service():
    repo = Repository()
    return repo, PartnerAdminService(repo, SimpleNamespace(now=lambda: NOW))


@pytest.mark.asyncio
async def test_accept_preserves_unpaid_source_and_adds_multiple_managers():
    repo, app = service()
    command = LeadReviewCommand(
        "review:1",
        ADMIN,
        LEAD,
        0,
        "accept",
        (MANAGER, OLD),
        "Согласовано сопровождение",
    )
    result = await app.review_lead(
        command, principal=PRINCIPAL, session=object()
    )
    assert result["state"] == "accepted" and result["version"] == 1
    assert result["source_state"] == "requested_unpaid"
    assert repo.memberships == {MANAGER, OLD}
    assert (
        await app.review_lead(command, principal=PRINCIPAL, session=object())
        == result
    )
    with pytest.raises(ValueError, match="lead_version_conflict"):
        await app.review_lead(
            LeadReviewCommand(
                "review:2", ADMIN, LEAD, 0, "reject", (), "Причина отказа"
            ),
            principal=PRINCIPAL,
            session=object(),
        )


@pytest.mark.asyncio
async def test_current_admin_authority_precedes_replay():
    repo, app = service()
    command = LeadReviewCommand(
        "review:1", ADMIN, LEAD, 0, "reject", (), "Нет подходящего менеджера"
    )
    await app.review_lead(command, principal=PRINCIPAL, session=object())
    repo.users[ADMIN] = OverrideUser(ADMIN, "active", False, "admin-native")
    with pytest.raises(ValueError, match="active_admin_required"):
        await app.review_lead(command, principal=PRINCIPAL, session=object())


@pytest.mark.asyncio
async def test_binding_correction_audits_actor_reason_and_replays():
    repo, app = service()
    command = BindingCorrectionCommand(
        "fix:1",
        ADMIN,
        CLIENT,
        OLD,
        NEW,
        "Исправление ошибочной первой привязки",
    )
    result = await app.correct_binding(
        command, principal=PRINCIPAL, session=object()
    )
    assert repo.binding == NEW
    assert repo.audits == [(ADMIN, command.reason, OLD, NEW)]
    assert result["previous_referrer_id"] == str(OLD)
    repo.users[NEW] = OverrideUser(NEW, "blocked", False, str(NEW))
    assert (
        await app.correct_binding(
            command, principal=PRINCIPAL, session=object()
        )
        == result
    )
    assert len(repo.audits) == 1


@pytest.mark.asyncio
async def test_binding_correction_rejects_self_referral_and_changed_source():
    repo, app = service()
    with pytest.raises(ValueError, match="self_referral_forbidden"):
        await app.correct_binding(
            BindingCorrectionCommand(
                "fix:1", ADMIN, CLIENT, OLD, CLIENT, "Техническая причина"
            ),
            principal=PRINCIPAL,
            session=object(),
        )
    with pytest.raises(ValueError, match="referral_binding_changed"):
        await app.correct_binding(
            BindingCorrectionCommand(
                "fix:2", ADMIN, CLIENT, NEW, OLD, "Техническая причина"
            ),
            principal=PRINCIPAL,
            session=object(),
        )
    assert repo.binding == OLD and repo.audits == []
