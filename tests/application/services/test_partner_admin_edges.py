"""Operational decisions require current authority and immutable sources."""

from dataclasses import replace
from uuid import UUID

import pytest

from tests.application.services.test_partner_admin_service import (
    ADMIN,
    CLIENT,
    LEAD,
    MANAGER,
    NEW,
    OLD,
    PRINCIPAL,
    service,
)
from ugc_bot.application.override_ports import OverrideUser
from ugc_bot.application.partner_admin_ports import (
    BindingCorrectionCommand,
    LeadReviewCommand,
)


def lead():
    return LeadReviewCommand(
        "lead", ADMIN, LEAD, 0, "accept", (MANAGER,), "Назначение проверено"
    )


def binding():
    return BindingCorrectionCommand(
        "binding", ADMIN, CLIENT, OLD, NEW, "Техническая ошибка"
    )


@pytest.mark.parametrize(
    "change",
    [
        dict(actor_id=UUID(int=0)),
        dict(operation_key=" "),
        dict(reason="x" * 4001),
        dict(lead_id=UUID(int=0)),
        dict(expected_version=True),
        dict(action="invalid"),
        dict(manager_ids=()),
        dict(manager_ids=(MANAGER, MANAGER)),
        dict(manager_ids=(UUID(int=0),)),
    ],
)
def test_lead_contract_rejects_invalid_authority_version_and_managers(change):
    with pytest.raises(ValueError):
        replace(lead(), **change)


def test_binding_contract_requires_real_referred_identity():
    with pytest.raises(ValueError, match="admin_review_identity_required"):
        replace(binding(), referred_id=UUID(int=0))


@pytest.mark.asyncio
async def test_context_requires_current_native_proof_and_valid_queue():
    _, app = service()
    assert (await app.context(ADMIN, principal=PRINCIPAL, session=object()))[
        "capabilities"
    ]["review_leads"] is True
    with pytest.raises(ValueError, match="financial_principal_changed"):
        await app.context(ADMIN, principal=None, session=object())
    with pytest.raises(ValueError, match="lead_queue_invalid"):
        await app.queue(ADMIN, page=True, principal=PRINCIPAL, session=object())


@pytest.mark.asyncio
async def test_missing_or_inactive_manager_cannot_accept():
    repo, app = service()
    repo.users[MANAGER] = OverrideUser(MANAGER, "blocked", False, str(MANAGER))
    with pytest.raises(ValueError, match="active_manager_required"):
        await app.review_lead(lead(), principal=PRINCIPAL, session=object())
    with pytest.raises(ValueError, match="lead_not_found"):
        await app.review_lead(
            replace(
                lead(), lead_id=UUID(int=999), action="reject", manager_ids=()
            ),
            principal=PRINCIPAL,
            session=object(),
        )


@pytest.mark.asyncio
async def test_terminal_review_cannot_be_rewritten_or_reused_with_new_payload():
    _, app = service()
    await app.review_lead(lead(), principal=PRINCIPAL, session=object())
    with pytest.raises(ValueError, match="idempotency_payload_conflict"):
        await app.review_lead(
            replace(lead(), reason="Другая причина"),
            principal=PRINCIPAL,
            session=object(),
        )
    with pytest.raises(ValueError, match="lead_already_reviewed"):
        await app.review_lead(
            replace(lead(), operation_key="other", expected_version=1),
            principal=PRINCIPAL,
            session=object(),
        )


@pytest.mark.asyncio
async def test_binding_needs_existing_active_target_and_real_change():
    repo, app = service()
    with pytest.raises(ValueError, match="referral_user_not_found"):
        await app.correct_binding(
            replace(binding(), referrer_id=UUID(int=999)),
            principal=PRINCIPAL,
            session=object(),
        )
    repo.users[NEW] = OverrideUser(NEW, "blocked", False, str(NEW))
    with pytest.raises(ValueError, match="active_referrer_required"):
        await app.correct_binding(
            binding(), principal=PRINCIPAL, session=object()
        )
    with pytest.raises(ValueError, match="referral_binding_unchanged"):
        await app.correct_binding(
            replace(binding(), referrer_id=OLD),
            principal=PRINCIPAL,
            session=object(),
        )
