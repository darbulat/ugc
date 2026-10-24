"""Declared synthetic approval facts, with no SQL or producer authority."""

from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace
from uuid import UUID

from tests.helpers.correction_commands import (
    HASH,
    NOW,
    Proofs,
    Repository,
    U,
    request,
)
from ugc_bot.application.correction_ports import (
    MatchSelectionRefund,
    RecordManualRefundObservation,
    ReviewSelectionRefund,
)
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.application.services.correction_service import CorrectionService


def environment(*, platform="telegram"):
    repo, proofs = Repository(), Proofs()
    service = CorrectionService(repo, proofs, SimpleNamespace(now=lambda: NOW))

    async def execute(command, *, principal=None):
        if principal is None:
            principal = AuthenticatedMessengerPrincipal(
                command.actor_id,
                platform,
                repo.actors[command.actor_id][
                    "telegram_id" if platform == "telegram" else "max_id"
                ],
            )
        return await service.execute(
            command, principal=principal, session=repo.session
        )

    return SimpleNamespace(
        repo=repo, proofs=proofs, service=service, execute=execute
    )


def review(result, **changes):
    return ReviewSelectionRefund(
        **(
            dict(
                actor_id=U[1],
                operation_key="review",
                reason="Synthetic separately authenticated review",
                case_id=UUID(result["case_id"]),
                expected_version=result["version"],
                expected_source_hash=HASH,
                decision="approve",
                evidence_reference="synthetic:approval-review",
                evidence_hash=HASH,
            )
            | changes
        )
    )


def observation(result=None, **changes):
    return RecordManualRefundObservation(
        **(
            dict(
                actor_id=U[1],
                operation_key="observation",
                reason="Synthetic retained original bank report",
                case_id=UUID(result["case_id"]) if result else None,
                known_order_id=U[3],
                known_capture_intent_id=U[4],
                original_payment_reference="synthetic-payment",
                bank_account_label="synthetic-bank",
                bank_reference="synthetic:refund",
                amount_minor=50000,
                currency="RUB",
                occurred_at=NOW,
                reported_component="selection",
                evidence_reference="synthetic:approval-observation",
                evidence_hash=HASH,
                expected_version=result["version"] if result else None,
            )
            | changes
        )
    )


def match(result, approved, observed, **changes):
    return MatchSelectionRefund(
        **(
            dict(
                actor_id=U[1],
                operation_key="match",
                reason="Synthetic exact new linked match",
                case_id=UUID(result["case_id"]),
                intent_id=UUID(approved["intent_id"]),
                observation_id=UUID(observed["observation_id"]),
                expected_version=result["version"],
                expected_source_hash=HASH,
                evidence_reference="synthetic:approval-match",
                evidence_hash=HASH,
            )
            | changes
        )
    )


async def early_report(env, *, unknown_case_owner=False):
    env.repo.scope = replace(
        env.repo.scope,
        bundle=None,
        payment_id=None,
        capture_id=None,
        source_hash=None,
        client_id=None if unknown_case_owner else env.repo.captured.client_id,
        order_id=None if unknown_case_owner else env.repo.captured.order_id,
        unavailable_reason="correction_capture_unavailable",
    )
    early = await env.execute(observation())
    retained = deepcopy(
        {
            kind: env.repo.rows[kind]
            for kind in ("cases", "intents", "observations")
        }
    )
    owners = deepcopy(env.proofs.rows)
    env.repo.scope = env.repo.captured
    attached = await env.execute(
        request(existing_case_id=UUID(early["case_id"]))
    )
    return early, attached, retained, owners


async def captured_approval(env):
    return await env.execute(review(await env.execute(request())))


def faithful_legacy_authority(env, approved):
    """Explicit synthetic old-format capsule; never an archived SQL writer."""
    approval = deepcopy(env.repo.rows["approvals"].pop())
    intent = env.repo.rows["intents"][0]
    for key in (
        "request_id",
        "capture_id",
        "payment_id",
        "source_hash",
        "bundle",
        "amount_minor",
        "currency",
        "review_version",
        "command_id",
        "recorded_at",
    ):
        intent[key] = approval[key]
    receipt = next(
        row
        for row in env.repo.rows["commands"]
        if row["command_id"] == approval["command_id"]
    )
    receipt["result"].pop("approval_id")
    env.repo.events = [
        replace(event, source_id=intent["intent_id"])
        if event.command_id == approval["command_id"]
        else event
        for event in env.repo.events
    ]
    return dict(approved, **{"approval_id": None})
