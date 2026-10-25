"""Manual bank evidence and frozen accompaniment refund rules."""

from dataclasses import asdict
from uuid import NAMESPACE_URL, uuid4, uuid5

from ugc_bot.application.collaboration_ports import CollaborationCommand
from ugc_bot.application.financial_ports import IssueBasis, IssuedObligation
from ugc_bot.application.native_principal_ports import require_current_principal
from ugc_bot.application.physical_proof_ports import (
    PhysicalProofConflict,
    PhysicalProofOwner,
    PhysicalProofUnavailable,
)
from ugc_bot.domain.corrections import correction_payload_hash
from ugc_bot.domain.financial import utc


class AccompanimentRefundService:
    def __init__(
        self,
        repository,
        ledger,
        physical_proofs,
        compensation,
        clock,
        lifecycle=None,
    ):
        self.repository, self.ledger = repository, ledger
        self.lifecycle = lifecycle
        self.physical_proofs, self.compensation, self.clock = (
            physical_proofs,
            compensation,
            clock,
        )

    async def _locked(self, command, principal, session):
        repo, ledger = self.repository, self.ledger.repository
        before = await repo.load_scope(command.paid_item_id, session=session)
        grounds = await ledger.list_item_grounds(
            command.paid_item_id, "management", session=session
        )
        work = before.record.collaboration if before.record else None
        users = {command.actor_id, before.capture.client_id} | {
            g.recipient_id for g in grounds
        }
        if work is not None:
            users.add(work.creator_id)
            if work.manager_id is not None:
                users.add(work.manager_id)
        await ledger.lock_recipients(
            tuple(sorted(users, key=str)), session=session
        )
        wallet_users = {g.recipient_id for g in grounds}
        if (
            work is not None
            and work.manager_id is not None
            and before.manager_earned
        ):
            wallet_users.add(work.manager_id)
        await ledger.lock_wallets(
            tuple((g, "RUB") for g in sorted(wallet_users, key=str)),
            session=session,
        )
        await repo.lock_scope(before, session=session)
        await ledger.lock_item(command.paid_item_id, session=session)
        current = await repo.load_scope(command.paid_item_id, session=session)
        fresh = await ledger.list_item_grounds(
            command.paid_item_id, "management", session=session
        )
        if current != before or any(g.recipient_id not in users for g in fresh):
            raise ValueError("financial_scope_changed_retry_required")
        actor = await repo.load_actor(command.actor_id, session=session)
        require_current_principal(
            principal,
            command.actor_id,
            actor.user_id if actor else None,
            actor.telegram_id if actor else None,
            actor.max_id if actor else None,
        )
        if actor is None or not actor.admin or actor.status != "active":
            raise PermissionError("active_admin_required")
        return current, fresh

    async def _replay(self, command, session):
        previous = await self.repository.get_command(
            command.actor_id, command.operation_key, session=session
        )
        if previous is not None:
            if previous[0] != correction_payload_hash(command):
                raise ValueError("idempotency_payload_conflict")
            return previous[1]
        return None

    async def _save(self, command, result, session):
        await self.repository.save_command(
            command.actor_id,
            command.operation_key,
            correction_payload_hash(command),
            result,
            session=session,
        )
        return result

    async def observe(self, command, *, session, principal=None):
        scope, _ = await self._locked(command, principal, session)
        previous = await self._replay(command, session)
        if previous is not None:
            return previous
        identity, observation = uuid4(), uuid4()
        claimed, blocker = False, None
        try:
            bank = self.physical_proofs.resolve_manual_identity(
                command.bank_account_label,
                command.bank_reference,
                direction="outgoing",
            )
            await self.physical_proofs.claim(
                bank,
                PhysicalProofOwner(
                    producer="refund",
                    intent_id=observation,
                    observation_id=observation,
                    command_id=identity,
                ),
                session=session,
            )
            claimed = True
        except (PhysicalProofConflict, PhysicalProofUnavailable) as exc:
            blocker = str(exc)
        now = utc(self.clock.now())
        await self.repository.append_observation(
            dict(
                asdict(command),
                observation_id=observation,
                command_id=identity,
                payment_id=scope.capture.payment_id,
                proof_claimed=claimed,
                recorded_at=now,
            ),
            session=session,
        )
        return await self._save(
            command,
            {
                "observation_id": str(observation),
                "proof_claimed": claimed,
                "blocker": blocker,
                "applied": False,
            },
            session,
        )

    async def apply(self, command, *, session, principal=None):
        scope, grounds = await self._locked(command, principal, session)
        previous = await self._replay(command, session)
        if previous is not None:
            return previous
        existing = await self.repository.application(
            command.observation_id, session=session
        )
        if existing is not None:
            if (existing["paid_item_id"], existing["payment_id"]) != (
                command.paid_item_id,
                scope.capture.payment_id,
            ):
                raise ValueError("accompaniment_bank_scope_mismatch")
            return await self._save(command, self._result(existing), session)
        if command.expected_work_version != scope.work_version:
            raise ValueError("collaboration_version_conflict")
        now = utc(self.clock.now())
        if now < scope.capture.captured_at or (
            scope.record is not None and now < scope.record.updated_at
        ):
            raise ValueError("accompaniment_fact_in_future")
        originals, rules, customer, manager = await self._assessment(
            scope, grounds, command, session=session
        )
        prior_customer, prior_manager = await self.repository.totals(
            command.paid_item_id, session=session
        )
        if customer <= prior_customer or manager < prior_manager:
            raise ValueError("accompaniment_cumulative_target_conflict")
        observation = await self.repository.observation(
            command.observation_id, session=session
        )
        self._require_observation(observation, scope, customer - prior_customer)
        application_id = uuid4()
        if not originals and scope.manager_earned:
            originals = [
                await self._assess_original_management(scope, now, session)
            ]
        if manager > prior_manager:
            await self.compensation.cancel(
                originals[0],
                target_minor=manager,
                already_cancelled_minor=prior_manager,
                case_id=application_id,
                refund_id=application_id,
                actor_id=command.actor_id,
                now=now,
                session=session,
            )
        fact = dict(
            application_id=application_id,
            observation_id=command.observation_id,
            paid_item_id=command.paid_item_id,
            payment_id=scope.capture.payment_id,
            assignment_id=scope.record.collaboration.assignment_id
            if scope.record
            else None,
            work_version=scope.work_version,
            stage=scope.work_stage,
            policy_version=scope.capture.policy.version,
            rules=rules.to_document(),
            customer_target_minor=customer,
            customer_delta_minor=customer - prior_customer,
            manager_target_minor=manager,
            manager_delta_minor=manager - prior_manager,
            actor_id=command.actor_id,
            reason=command.reason,
            evidence_reference=command.evidence_reference,
            evidence_hash=command.evidence_hash,
            recorded_at=now,
        )
        await self.repository.append_application(fact, session=session)
        return await self._save(command, self._result(fact), session)

    async def _assessment(self, scope, grounds, command, *, session):
        item = next(
            i
            for i in scope.capture.items
            if i.paid_item_id == command.paid_item_id
        )
        rules = scope.capture.policy.refund_rules
        if item.accompaniment_minor != 120000 or rules is None:
            raise ValueError("accompaniment_refund_rules_required")
        originals = [
            await self.ledger.repository.get_issue(
                g.business_key, session=session
            )
            for g in grounds
        ]
        if len(originals) > 1 or any(
            o is None
            or o.basis.kind != "management"
            or o.basis.payment_id != scope.capture.payment_id
            for o in originals
        ):
            raise ValueError("accompaniment_manager_ground_review_required")
        if scope.record is None:
            if originals:
                raise ValueError("accompaniment_manager_ground_review_required")
            customer = self._target(
                None, command.reviewed_customer_target_minor
            )
            manager = self._target(0, command.reviewed_manager_target_minor)
            if not 0 <= customer <= 120000:
                raise ValueError("accompaniment_refund_capacity_exceeded")
            return originals, rules, customer, manager
        earned = 60000 if originals or scope.manager_earned else 0
        assessment = rules.assess_accompaniment_refund(
            stage=scope.record.collaboration.state.value,
            paid_minor=120000,
            manager_earned_minor=earned,
        )
        customer = self._target(
            assessment.customer_refund_minor,
            command.reviewed_customer_target_minor,
        )
        manager = self._target(
            assessment.manager_adjustment_minor,
            command.reviewed_manager_target_minor,
        )
        if not 0 <= customer <= 120000 or not 0 <= manager <= earned:
            raise ValueError("accompaniment_refund_capacity_exceeded")
        return originals, rules, customer, manager

    @staticmethod
    def _target(assessed, reviewed):
        if assessed is None:
            if reviewed is None:
                raise ValueError("accompaniment_manual_review_required")
            return reviewed
        if reviewed is not None and assessed != reviewed:
            raise ValueError("accompaniment_review_conflicts_frozen_rules")
        return assessed

    async def _assess_original_management(self, scope, now, session):
        """Delayed original success assessment, inside this explicit correction.

        The trusted SQL scope proves actual successful funded management. The
        same capture key and basis make a later ordinary consumer a replay.
        """
        capture, record = scope.capture, scope.record
        work = record.collaboration
        if work.manager_id is None or work.state not in (
            "success_final",
            "available",
        ):
            raise ValueError("accompaniment_manager_ground_review_required")
        original = await self.ledger.issue(
            IssueBasis(
                business_key=f"management:{capture.payment_id}:{record.paid_item_id}:{work.assignment_id}",
                kind="management",
                recipient_id=work.manager_id,
                paid_item_id=record.paid_item_id,
                order_id=record.order_id,
                assignment_id=work.assignment_id,
                referred_user_id=work.creator_id,
                payment_id=capture.payment_id,
                currency="RUB",
                base_minor=60000,
                rate_bps=None,
                policy_version=capture.policy.version,
                snapshot_at=capture.captured_at,
                registered_at=None,
                verified_count=None,
                event_id=str(capture.event_id),
                reason="successful_funded_management",
                actor_id=None,
                actor_kind="system",
                system_actor="work_entitlement",
            ),
            recorded_at=now,
            session=session,
        )
        if not isinstance(original, IssuedObligation):
            raise ValueError("accompaniment_manager_ground_review_required")
        return original

    async def review_management(self, command, *, session, principal=None):
        scope, grounds = await self._locked(command, principal, session)
        previous = await self._replay(command, session)
        if previous is not None:
            return previous
        if self.lifecycle is None or scope.record is None:
            raise ValueError("accompaniment_management_review_unavailable")
        if command.expected_work_version != scope.work_version:
            raise ValueError("collaboration_version_conflict")
        application = await self.repository.latest_application(
            command.paid_item_id, session=session
        )
        if (
            application is None
            or application["application_id"] != command.application_id
        ):
            raise ValueError("accompaniment_management_application_conflict")
        net = 120000 - application["customer_target_minor"]
        self._require_management_review(scope, grounds, command.decision, net)
        review_id = uuid4()
        operation = "accompaniment-management:" + str(review_id)
        event_id = uuid5(
            NAMESPACE_URL,
            f"ugc:collaboration:{scope.record.collaboration.assignment_id}:{operation}",
        )
        now = utc(self.clock.now())
        await self.repository.append_management_review(
            dict(
                review_id=review_id,
                application_id=command.application_id,
                paid_item_id=command.paid_item_id,
                assignment_id=scope.record.collaboration.assignment_id,
                work_version=scope.record.version,
                decision=command.decision,
                customer_net_minor=net,
                source_event_id=event_id,
                actor_id=command.actor_id,
                reason=command.reason,
                evidence_reference=command.evidence_reference,
                evidence_hash=command.evidence_hash,
                recorded_at=now,
            ),
            session=session,
        )
        record = await self.lifecycle.execute(
            CollaborationCommand(
                assignment_id=scope.record.collaboration.assignment_id,
                action="review_management",
                operation_key=operation,
                expected_version=scope.record.version,
                actor_id=command.actor_id,
                reason=command.reason,
                evidence="accompaniment-management-review:" + str(review_id),
            ),
            session=session,
        )
        return await self._save(
            command,
            {
                "review_id": str(review_id),
                "decision": command.decision,
                "work_version": record.version,
            },
            session,
        )

    @staticmethod
    def _require_management_review(scope, grounds, decision, net):
        state = scope.record.collaboration.state
        if decision == "continue":
            if net < 60000 or state in (
                "disputed",
                "rejected",
                "unconfirmed_expired",
            ):
                raise ValueError(
                    "accompaniment_management_continuation_unfunded"
                )
        elif scope.manager_earned or grounds:
            raise ValueError(
                "accompaniment_earned_management_requires_compensation"
            )

    @staticmethod
    def _require_observation(observation, scope, amount):
        if observation is None or (
            observation["paid_item_id"],
            observation["payment_id"],
            observation["original_payment_reference"],
        ) != (
            scope.paid_item_id,
            scope.capture.payment_id,
            scope.original_payment_reference,
        ):
            raise ValueError("accompaniment_bank_scope_mismatch")
        if not observation["proof_claimed"]:
            raise ValueError("physical_proof_unavailable")
        if (
            observation["currency"] != "RUB"
            or observation["amount_minor"] != amount
        ):
            raise ValueError("accompaniment_bank_amount_mismatch")

    @staticmethod
    def _result(fact):
        return {
            "application_id": str(fact["application_id"]),
            "applied": True,
            "customer_refund_minor": fact["customer_delta_minor"],
            "manager_adjustment_minor": fact["manager_delta_minor"],
        }
