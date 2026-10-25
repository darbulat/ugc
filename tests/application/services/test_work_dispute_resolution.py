"""Only a current administrator resolves a persisted objection with evidence."""

from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest

from tests.application.services.test_collaboration_service import (
    claimed,
    execute,
)


async def disputed():
    service, repo, scope, clock, Command, admin, current = await claimed()
    current = await execute(
        service,
        repo,
        Command(
            assignment_id=scope.assignment_id,
            action="dispute",
            actor_id=scope.client_id,
            operation_key="actual-objection",
            expected_version=current.version,
            reason="Deliverable differs from the accepted brief",
        ),
    )
    return service, repo, scope, clock, Command, admin, current


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action,state",
    (("resolve_success", "success_final"), ("resolve_failure", "rejected")),
)
async def test_admin_resolution_keeps_evidence_original_case_and_new_hold(
    action, state
):
    service, repo, scope, clock, Command, admin, current = await disputed()
    clock.at += timedelta(hours=1)
    command = Command(
        assignment_id=scope.assignment_id,
        action=action,
        actor_id=admin,
        operation_key="review-dispute",
        expected_version=current.version,
        reason="Reviewed the agreed brief and actual content",
        evidence="protected-evidence:actual-review",
    )
    result = await execute(service, repo, command)
    assert result.collaboration.state == state
    events = tuple(repo.events.values())
    saved = events[-1]
    assert saved.parameters["evidence"] == command.evidence
    assert saved.parameters["reason"] == command.reason
    assert saved.parameters["case_id"] == events[-2].parameters["case_id"]
    assert saved.parameters["source_dispute_event_id"] == str(
        events[-2].event_id
    )
    assert await execute(service, repo, command) == result
    if action == "resolve_success":
        assert result.collaboration.success_final_at == clock.at
        assert result.collaboration.available_at == clock.at + timedelta(
            days=14
        )
    else:
        assert result.collaboration.success_final_at is None
        assert not repo.schedules
    repo.actors[admin] = replace(repo.actors[admin], is_admin=False)
    with pytest.raises(PermissionError, match="active_admin_required"):
        await execute(service, repo, command)


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ("reason", "evidence"))
async def test_review_needs_substantive_reason_and_evidence(field):
    service, repo, scope, _, Command, admin, current = await disputed()
    args = dict(reason="Actual review", evidence="protected:proof")
    args[field] = " "
    with pytest.raises(ValueError, match="resolution_evidence_required"):
        await execute(
            service,
            repo,
            Command(
                assignment_id=scope.assignment_id,
                action="resolve_success",
                actor_id=admin,
                operation_key="incomplete-review",
                expected_version=current.version,
                **args,
            ),
        )


@pytest.mark.asyncio
async def test_a_party_cannot_resolve_their_own_disputed_result():
    service, repo, scope, _, Command, _, current = await disputed()
    with pytest.raises(PermissionError, match="active_admin_required"):
        await execute(
            service,
            repo,
            Command(
                assignment_id=scope.assignment_id,
                action="resolve_failure",
                actor_id=scope.client_id,
                operation_key="self-review",
                expected_version=current.version,
                reason="I prefer a refund",
                evidence="my own request",
            ),
        )


@pytest.mark.asyncio
async def test_dispute_queue_is_current_admin_only_and_excludes_resolved_work():
    service, repo, scope, _, Command, admin, current = await disputed()
    async with repo.transaction() as session:
        page = await service.list_disputes(admin, limit=1, session=session)
        assert page["items"][0]["assignment_id"] == str(scope.assignment_id)
        assert page["items"][0]["version"] == current.version
        assert (
            page["items"][0]["reason"] == current.collaboration.dispute_reason
        )
        assert not page["has_more"] and page["next_cursor"] is None
        with pytest.raises(PermissionError, match="active_admin_required"):
            await service.list_disputes(scope.client_id, session=session)
        with pytest.raises(ValueError, match="invalid_dispute_page"):
            await service.list_disputes(admin, limit=True, session=session)
        assert not (
            await service.list_disputes(admin, cursor=uuid4(), session=session)
        )["has_more"]
    await execute(
        service,
        repo,
        Command(
            assignment_id=scope.assignment_id,
            action="resolve_failure",
            actor_id=admin,
            operation_key="review-queue",
            expected_version=current.version,
            reason="Review",
            evidence="private-evidence",
        ),
    )
    async with repo.transaction() as session:
        assert not (await service.list_disputes(admin, session=session))[
            "items"
        ]
    repo.actors[admin] = replace(repo.actors[admin], status="disabled")
    async with repo.transaction() as session:
        with pytest.raises(PermissionError, match="active_admin_required"):
            await service.list_disputes(admin, session=session)


@pytest.mark.asyncio
async def test_admin_dispute_view_is_explicit_and_ordinary_view_stays_private():
    from ugc_bot.application.native_principal_ports import (
        AuthenticatedMessengerPrincipal,
    )

    service, repo, scope, _, Command, admin, current = await disputed()
    repo.actors[admin] = replace(repo.actors[admin], telegram_id="admin-native")
    proof = AuthenticatedMessengerPrincipal(admin, "telegram", "admin-native")
    async with repo.transaction() as session:
        with pytest.raises(
            PermissionError, match="collaboration_view_forbidden"
        ):
            await service.get_authenticated(
                scope.assignment_id, proof, session=session
            )
        record, is_current, actions = await service.get_for_admin(
            admin, scope.assignment_id, principal=proof, session=session
        )
        assert record == current and is_current
        assert actions == ("resolve_success", "resolve_failure")
        with pytest.raises(ValueError, match="financial_principal_changed"):
            await service.get_for_admin(
                scope.client_id,
                scope.assignment_id,
                principal=proof,
                session=session,
            )
        assert (
            await service.get_for_admin(
                admin, uuid4(), principal=proof, session=session
            )
            is None
        )
        result, _, actions = await service.execute_authenticated(
            Command(
                assignment_id=scope.assignment_id,
                actor_id=admin,
                action="resolve_failure",
                operation_key="native-admin-resolution",
                expected_version=current.version,
                reason="Reviewed actual brief dispute",
                evidence="private:admin-proof",
            ),
            proof,
            session=session,
        )
        assert result.collaboration.state == "rejected" and not actions
    repo.actors[admin] = replace(repo.actors[admin], is_admin=False)
    async with repo.transaction() as session:
        with pytest.raises(PermissionError, match="active_admin_required"):
            await service.get_for_admin(
                admin, scope.assignment_id, principal=proof, session=session
            )
