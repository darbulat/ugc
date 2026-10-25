"""Persisted work lifecycle; item lock -> state/event/outbox, never wallets.

Financial consumers MUST re-read this state under their user/wallet/item
barrier before release or payout. An outbox projection may lag a dispute.
Do not nest wallet-writing commands inside this item-locked component.
"""

from dataclasses import asdict, replace
from uuid import NAMESPACE_URL, UUID, uuid5

from ugc_bot.application.collaboration_ports import (
    CollaborationActor,
    CollaborationCommand,
    CollaborationEvent,
    CollaborationNotice,
    CollaborationPrincipalScope,
    CollaborationRecord,
    CollaborationReleaseSchedule,
    CollaborationRepository,
    canonical,
    command_hash,
)
from ugc_bot.application.financial_ports import Clock
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
    require_current_principal,
)
from ugc_bot.domain.collaboration import Collaboration, CollaborationState
from ugc_bot.domain.financial import utc


class CollaborationService:
    async def list_disputes(
        self, actor_id, *, principal=None, limit=25, cursor=None, session
    ):
        if (
            type(limit) is not int
            or not 1 <= limit <= 100
            or (cursor is not None and not isinstance(cursor, UUID))
        ):
            raise ValueError("invalid_dispute_page")
        actor = await self.repository.lock_admin_actor(
            actor_id, session=session
        )
        require_current_principal(
            principal,
            actor_id,
            actor.user_id if actor else None,
            actor.telegram_id if actor else None,
            actor.max_id if actor else None,
        )
        if actor is None or not actor.is_admin or actor.status != "active":
            raise PermissionError("active_admin_required")
        records = await self.repository.list_disputes(
            limit + 1, cursor, session=session
        )
        items = tuple(
            {
                "assignment_id": str(r.collaboration.assignment_id),
                "order_id": str(r.order_id),
                "version": r.version,
                "reason": r.collaboration.dispute_reason,
                "evidence": r.collaboration.evidence,
                "disputed_at": r.collaboration.disputed_at.isoformat(),
            }
            for r in records[:limit]
        )
        return {
            "items": items,
            "has_more": len(records) > limit,
            "next_cursor": items[-1]["assignment_id"]
            if len(records) > limit
            else None,
        }

    def __init__(self, repository: CollaborationRepository, clock: Clock):
        self.repository = repository
        self.clock = clock

    async def get_authenticated(
        self,
        assignment_id: UUID,
        principal: AuthenticatedMessengerPrincipal,
        *,
        session: object,
    ) -> tuple[CollaborationRecord, bool, tuple[str, ...]] | None:
        if not isinstance(principal, AuthenticatedMessengerPrincipal):
            raise ValueError("financial_principal_changed")
        prepared = await self.repository.prepare_principal_scope(
            assignment_id,
            principal.user_id,
            principal,
            session=session,
        )
        if prepared is None:
            return None
        record = await self.get_for_actor(
            assignment_id,
            principal.user_id,
            session=session,
            expected_scope=prepared,
        )
        if record is None:
            return None
        current, actions = await self.actions_for_actor(
            record,
            principal.user_id,
            session=session,
            expected_scope=prepared,
        )
        return record, current, actions

    async def execute_authenticated(
        self,
        command: CollaborationCommand,
        principal: AuthenticatedMessengerPrincipal,
        *,
        session: object,
    ) -> tuple[CollaborationRecord, bool, tuple[str, ...]]:
        self._validate_command(command)
        if (
            not isinstance(principal, AuthenticatedMessengerPrincipal)
            or command.actor_id != principal.user_id
            or command.system_actor is not None
        ):
            raise ValueError("financial_principal_changed")
        prepared = await self.repository.prepare_principal_scope(
            command.assignment_id,
            principal.user_id,
            principal,
            session=session,
        )
        if prepared is None:
            raise ValueError("assignment_not_found")
        record = await self.execute(
            command,
            session=session,
            expected_scope=prepared,
        )
        current, actions = await self.actions_for_actor(
            record,
            principal.user_id,
            session=session,
            expected_scope=prepared,
            admin_review=command.action
            in ("resolve_success", "resolve_failure"),
        )
        return record, current, actions

    async def get_for_admin(
        self, actor_id, assignment_id, *, principal, session
    ):
        if (
            not isinstance(principal, AuthenticatedMessengerPrincipal)
            or principal.user_id != actor_id
        ):
            raise ValueError("financial_principal_changed")
        prepared = await self.repository.prepare_principal_scope(
            assignment_id, actor_id, principal, session=session
        )
        if prepared is None:
            return None
        scope = await self.repository.lock_scope(
            assignment_id, session=session, expected_scope=prepared
        )
        actor = await self.repository.load_actor(actor_id, session=session)
        self._authorize(
            CollaborationCommand(
                assignment_id=assignment_id,
                action="admin_view",
                actor_id=actor_id,
                operation_key="dispute-review-view",
                expected_version=0,
            ),
            scope,
            actor,
        )
        record = await self.repository.get(assignment_id, session=session)
        if record is None:
            return None
        current, actions = await self.actions_for_actor(
            record,
            actor_id,
            session=session,
            expected_scope=prepared,
            admin_review=True,
        )
        return record, current, actions

    async def actions_for_actor(
        self,
        record: CollaborationRecord,
        actor_id: UUID,
        *,
        session: object,
        expected_scope: CollaborationPrincipalScope | None = None,
        admin_review: bool = False,
    ) -> tuple[bool, tuple[str, ...]]:
        """Current UI affordances assessed in the item's caller transaction.

        Commands still authorize and validate every submitted action. An old
        idempotent result offers no actions on that old version.
        """
        work = record.collaboration
        scope = await self.repository.lock_scope(
            work.assignment_id, session=session, expected_scope=expected_scope
        )
        actor = await self.repository.load_actor(actor_id, session=session)
        view = CollaborationCommand(
            assignment_id=work.assignment_id,
            action="admin_view" if admin_review else "view",
            actor_id=actor_id,
            operation_key="capabilities",
            expected_version=record.version,
        )
        self._authorize(view, scope, actor)
        current = await self.repository.get(work.assignment_id, session=session)
        is_current = (
            scope.valid_to is None
            and current is not None
            and current.version == record.version
            and scope.selection_funded
            and scope.captured_at is not None
            and scope.policy_version == record.policy_version
            and (scope.client_id, scope.creator_id, scope.manager_id)
            == (work.client_id, work.creator_id, work.manager_id)
        )
        at = utc(self.clock.now())
        if not is_current or at < record.updated_at or at < scope.valid_from:
            return is_current, ()
        actions = []
        for action in self._candidate_actions(work, at):
            if admin_review and action not in (
                "resolve_success",
                "resolve_failure",
            ):
                continue
            if action in ("agree", "dispute") and actor_id == work.claimant_id:
                continue
            try:
                self._authorize(replace(view, action=action), scope, actor)
            except PermissionError:
                continue
            actions.append(action)
        return is_current, tuple(actions)

    @staticmethod
    def _candidate_actions(work, at):
        if work.state in (
            CollaborationState.ASSIGNED,
            CollaborationState.IN_PROGRESS,
        ):
            if at >= work.first_claim_deadline:
                return ()
            return (
                "start"
                if work.state == CollaborationState.ASSIGNED
                else "claim",
                "extend_due",
                "request_confirmation",
            )
        if work.state == CollaborationState.SUCCESS_CLAIMED:
            actions = ["extend_due"]
            if at < work.objection_deadline:
                return (*actions, "agree", "dispute")
            return (*actions, "agree")
        if work.state == CollaborationState.DISPUTED:
            return ("resolve_success", "resolve_failure")
        return ()

    async def get_for_actor(
        self,
        assignment_id: UUID,
        actor_id: UUID,
        *,
        session: object,
        expected_scope: CollaborationPrincipalScope | None = None,
    ) -> CollaborationRecord | None:
        """Own private state, including a party's historical assignment."""
        command = CollaborationCommand(
            assignment_id=assignment_id,
            action="view",
            actor_id=actor_id,
            operation_key="view",
            expected_version=0,
        )
        self._validate_actor(command)
        try:
            scope = await self.repository.lock_scope(
                assignment_id, session=session, expected_scope=expected_scope
            )
        except ValueError as error:
            if str(error) != "assignment_not_found":
                raise
            return None
        actor = await self.repository.load_actor(actor_id, session=session)
        self._authorize(command, scope, actor)
        return await self.repository.get(assignment_id, session=session)

    async def execute(
        self,
        command: CollaborationCommand,
        *,
        session: object,
        expected_scope: CollaborationPrincipalScope | None = None,
    ) -> CollaborationRecord:
        self._validate_command(command)
        repo = self.repository
        scope = await repo.lock_scope(
            command.assignment_id,
            session=session,
            expected_scope=expected_scope,
        )
        actor = (
            await repo.load_actor(command.actor_id, session=session)
            if command.actor_id is not None
            else None
        )
        self._authorize(command, scope, actor)
        previous = await repo.get_command(
            command.assignment_id, command.operation_key, session=session
        )
        digest = command_hash(command)
        if previous is not None:
            if previous.payload_hash != digest:
                raise ValueError("idempotency_payload_conflict")
            return previous.result
        self._require_current_paid_scope(scope)
        assert scope.captured_at is not None
        current = await repo.get(command.assignment_id, session=session)
        version = current.version if current else 0
        if command.expected_version != version:
            raise ValueError("collaboration_version_conflict")
        at = utc(self.clock.now())
        if at < utc(scope.valid_from) or at < utc(scope.captured_at):
            raise ValueError("collaboration_time_conflict")
        if command.action == "notice":
            if command.notice_id is None:
                raise ValueError("objection_notice_required")
            notice = await repo.get_notice(command.notice_id, session=session)
            if (
                notice is None
                or notice.assignment_id != scope.assignment_id
                or notice.purpose != "objection"
            ):
                raise ValueError("objection_notice_required")
        result = self._transition(command, scope, current, at)
        event_id = uuid5(
            NAMESPACE_URL,
            f"ugc:collaboration:{scope.assignment_id}:{command.operation_key}",
        )
        parameters = await self._event_parameters(
            command, current, event_id, session=session
        )
        event = CollaborationEvent(
            event_id,
            scope.assignment_id,
            command.operation_key,
            digest,
            self._event_type(command, current, result),
            command.actor_id,
            command.system_actor,
            parameters,
            result,
            at,
        )
        notices = self._notices(command.action, event)
        schedule = self._schedule(event, current)
        await repo.persist(
            event, notices=notices, schedule=schedule, session=session
        )
        return result

    async def _event_parameters(self, command, current, event_id, *, session):
        parameters = canonical(asdict(command))
        if command.action == "dispute":
            parameters["case_id"] = str(
                uuid5(NAMESPACE_URL, f"ugc:collaboration-case:{event_id}")
            )
        if command.action not in ("resolve_success", "resolve_failure"):
            return parameters
        original = await self.repository.get_event_for_version(
            command.assignment_id, current.version, session=session
        )
        if (
            original is None
            or original.event_type != "financial.collaboration.disputed"
            or original.result != current
            or not original.parameters.get("case_id")
        ):
            raise ValueError("work_dispute_source_missing")
        parameters["case_id"] = original.parameters["case_id"]
        parameters["source_dispute_event_id"] = str(original.event_id)
        return parameters

    @staticmethod
    def _validate_command(command):
        if command.action not in (
            "assign",
            "start",
            "claim",
            "request_confirmation",
            "agree",
            "dispute",
            "extend_due",
            "notice",
            "advance",
            "resolve_success",
            "resolve_failure",
            "review_management",
        ):
            raise ValueError("unsupported_collaboration_command")
        if not isinstance(command.operation_key, str) or not (
            command.operation_key.strip() and len(command.operation_key) <= 200
        ):
            raise ValueError("command_key_required")
        if (
            type(command.expected_version) is not int
            or command.expected_version < 0
        ):
            raise ValueError("collaboration_version_required")
        if (
            not isinstance(command.assignment_id, UUID)
            or command.assignment_id.int == 0
        ):
            raise ValueError("assignment_identity_required")
        CollaborationService._validate_actor(command)

    @staticmethod
    def _validate_actor(command):
        producer = {
            "notice": "collaboration_notifier",
            "advance": "collaboration_scheduler",
        }.get(command.action)
        if producer is not None:
            if command.actor_id is not None or command.system_actor != producer:
                raise PermissionError("trusted_collaboration_producer_required")
            if command.action == "notice":
                CollaborationService._validate_notice(command)
            return
        if not isinstance(command.actor_id, UUID) or command.actor_id.int == 0:
            raise PermissionError("authenticated_actor_required")
        if command.system_actor is not None:
            raise PermissionError("ambiguous_actor")

    @staticmethod
    def _validate_notice(command):
        if type(command.accepted) is not bool or command.channel not in (
            "telegram",
            "max",
        ):
            raise ValueError("notice_result_required")
        proof = (
            command.external_reference if command.accepted else command.reason
        )
        if not isinstance(proof, str) or not proof.strip():
            raise ValueError("notice_reference_or_error_required")

    @staticmethod
    def _require_current_paid_scope(scope):
        if scope.valid_to is not None:
            raise ValueError("assignment_not_current")
        if (
            not scope.policy_version
            or scope.captured_at is None
            or not scope.selection_funded
        ):
            raise ValueError("captured_selection_required")
        if scope.client_id == scope.creator_id:
            raise ValueError("distinct_collaboration_parties_required")

    @staticmethod
    def _authorize(command, scope, actor: CollaborationActor | None):
        if command.system_actor is not None:
            CollaborationService._validate_actor(command)
            return
        if actor is None or actor.status not in (
            "active",
            "pause",
            "bot_blocked",
        ):
            raise PermissionError("active_actor_required")
        is_client = actor.user_id == scope.client_id and actor.is_client
        is_creator = actor.user_id == scope.creator_id and actor.is_creator
        is_manager = (
            actor.user_id == scope.manager_id
            and scope.order_id in actor.manager_order_ids
            and scope.valid_to is None
        )
        party = (is_client or is_creator, "collaboration_party_required")
        assigned = (is_client or is_manager, "assignment_actor_required")
        client = (is_client, "client_consent_required")
        rules = {
            "admin_view": (
                actor.is_admin and actor.status == "active",
                "active_admin_required",
            ),
            "review_management": (
                actor.is_admin and actor.status == "active",
                "active_admin_required",
            ),
            "resolve_success": (
                actor.is_admin and actor.status == "active",
                "active_admin_required",
            ),
            "resolve_failure": (
                actor.is_admin and actor.status == "active",
                "active_admin_required",
            ),
            "assign": client,
            "extend_due": client,
            "claim": party,
            "agree": party,
            "dispute": party,
            "start": assigned,
            "request_confirmation": assigned,
            "view": (
                is_client or is_creator or is_manager,
                "collaboration_view_forbidden",
            ),
        }
        rule = rules.get(command.action)
        if rule is None:
            raise ValueError("unsupported_collaboration_command")
        if not rule[0]:
            raise PermissionError(rule[1])

    @staticmethod
    def _transition(command, scope, current, at):
        if command.action == "assign":
            if current is not None:
                raise ValueError("collaboration_already_assigned")
            if (
                not isinstance(command.terms_reference, str)
                or not command.terms_reference.strip()
            ):
                raise ValueError("agreed_terms_required")
            collaboration = Collaboration(
                assignment_id=scope.assignment_id,
                client_id=scope.client_id,
                creator_id=scope.creator_id,
                manager_id=scope.manager_id,
                due_at=command.due_at,
                agreed_at=at,
            )
            return CollaborationRecord(
                collaboration,
                scope.paid_item_id,
                scope.order_id,
                scope.policy_version,
                command.terms_reference.strip(),
                1,
                at,
            )
        if current is None:
            raise ValueError("collaboration_not_found")
        collaboration = current.collaboration
        if (
            collaboration.client_id != scope.client_id
            or collaboration.creator_id != scope.creator_id
            or collaboration.manager_id != scope.manager_id
            or current.paid_item_id != scope.paid_item_id
            or current.order_id != scope.order_id
            or current.policy_version != scope.policy_version
        ):
            raise ValueError("collaboration_scope_changed")
        if at < current.updated_at:
            raise ValueError("collaboration_time_conflict")
        collaboration = CollaborationService._apply(command, collaboration, at)
        return replace(
            current,
            collaboration=collaboration,
            version=current.version + 1,
            updated_at=at,
        )

    @staticmethod
    def _apply(command, work, at):
        actions = {
            "review_management": lambda: (
                CollaborationService._management_review(command, work)
            ),
            "resolve_success": lambda: work.resolve_dispute(
                success=True,
                reason=command.reason,
                evidence=command.evidence,
                at=at,
            ),
            "resolve_failure": lambda: work.resolve_dispute(
                success=False,
                reason=command.reason,
                evidence=command.evidence,
                at=at,
            ),
            "start": lambda: work.start(actor_id=command.actor_id, at=at),
            "claim": lambda: work.claim_success(
                actor_id=command.actor_id, evidence=command.evidence, at=at
            ),
            "agree": lambda: work.agree(actor_id=command.actor_id, at=at),
            "dispute": lambda: work.dispute(
                actor_id=command.actor_id, reason=command.reason, at=at
            ),
            "notice": lambda: work.record_notice(
                accepted=command.accepted, at=at
            ),
            "advance": lambda: work.advance(at=at),
            "extend_due": lambda: CollaborationService._extend(
                command, work, at
            ),
            "request_confirmation": lambda: CollaborationService._request(
                work, at
            ),
        }
        return actions[command.action]()

    @staticmethod
    def _management_review(command, work):
        if (
            not isinstance(command.reason, str)
            or not command.reason.strip()
            or not isinstance(command.evidence, str)
            or not command.evidence.startswith(
                "accompaniment-management-review:"
            )
        ):
            raise ValueError("accompaniment_management_review_source_required")
        return work

    @staticmethod
    def _extend(command, work, at):
        if not all(
            isinstance(x, str) and x.strip()
            for x in (command.reason, command.terms_reference)
        ):
            raise ValueError("extension_consent_and_reason_required")
        return work.extend_due(
            actor_id=command.actor_id,
            due_at=command.due_at,
            expected_due_version=command.expected_due_version,
            at=at,
        )

    @staticmethod
    def _request(work, at):
        if (
            work.state
            not in (CollaborationState.ASSIGNED, CollaborationState.IN_PROGRESS)
            or at >= work.first_claim_deadline
        ):
            raise ValueError("confirmation_request_state_conflict")
        return work

    @staticmethod
    def _event_type(command, current, result):
        state = result.collaboration.state
        if state == CollaborationState.SUCCESS_FINAL and (
            current is None or current.collaboration.state != state
        ):
            suffix = "success_final"
        elif command.action == "advance":
            suffix = {
                CollaborationState.AVAILABLE: "hold_matured",
                CollaborationState.UNCONFIRMED_EXPIRED: "expired",
            }.get(state, "checked")
        elif command.action == "notice":
            suffix = "notice_accepted" if command.accepted else "notice_failed"
        else:
            suffix = {
                "claim": "success_claimed",
                "dispute": "disputed",
                "assign": "assigned",
                "start": "started",
                "extend_due": "due_extended",
                "request_confirmation": "confirmation_requested",
                "resolve_failure": "rejected",
                "review_management": "management_reviewed",
            }[command.action]
        return "financial.collaboration." + suffix

    @staticmethod
    def _schedule(event, current):
        work = event.result.collaboration
        if (
            work.state != CollaborationState.SUCCESS_FINAL
            or current.collaboration.state == CollaborationState.SUCCESS_FINAL
        ):
            return None
        return CollaborationReleaseSchedule(
            uuid5(NAMESPACE_URL, f"ugc:work-release:{event.event_id}"),
            event.assignment_id,
            event.event_id,
            work.success_final_at,
            work.available_at,
        )

    @staticmethod
    def _notices(action, event):
        if action not in ("claim", "request_confirmation"):
            return ()
        work = event.result.collaboration
        if action == "request_confirmation":
            return tuple(
                CollaborationNotice(
                    uuid5(
                        NAMESPACE_URL,
                        f"ugc:confirmation:{event.assignment_id}:{recipient}",
                    ),
                    event.assignment_id,
                    event.event_id,
                    "confirmation",
                    recipient,
                    event.occurred_at,
                )
                for recipient in (work.client_id, work.creator_id)
            )
        recipient = (
            work.client_id
            if work.claimant_id == work.creator_id
            else work.creator_id
        )
        return (
            CollaborationNotice(
                uuid5(NAMESPACE_URL, f"ugc:objection:{event.event_id}"),
                event.assignment_id,
                event.event_id,
                "objection",
                recipient,
                event.occurred_at,
            ),
        )
