"""Debt decreases only after a reviewed, recognized incoming repayment."""

from dataclasses import asdict
from uuid import NAMESPACE_URL, UUID, uuid5

from ugc_bot.application.financial_ports import JournalMovement
from ugc_bot.application.native_principal_ports import require_current_principal
from ugc_bot.application.physical_proof_ports import (
    PhysicalProofConflict,
    PhysicalProofOwner,
    PhysicalProofUnavailable,
)
from ugc_bot.application.services.financial_reconciliation_service import (
    FinancialReconciliationService,
)
from ugc_bot.domain.corrections import correction_payload_hash
from ugc_bot.domain.financial import utc


def command_id(command):
    return uuid5(
        NAMESPACE_URL,
        f"ugc:repayment:{command.actor_id}:{len(command.operation_key)}:{command.operation_key}",
    )


class DebtRecoveryService:
    def __init__(self, repository, ledger, physical_proofs, clock):
        self.repository, self.ledger, self.physical_proofs, self.clock = (
            repository,
            ledger,
            physical_proofs,
            clock,
        )

    async def context(
        self, actor_id, *, session, principal=None, page=0, limit=25
    ):
        if (
            type(page) is not int
            or not 0 <= page <= 100000
            or type(limit) is not int
            or not 1 <= limit <= 100
        ):
            raise ValueError("repayment_invalid_page")
        from types import SimpleNamespace

        command = SimpleNamespace(actor_id=actor_id)
        await self.ledger.repository.lock_recipients(
            (actor_id,), session=session
        )
        await self._admin(command, principal, session)
        cases = await self.repository.cases(
            limit=limit + 1, offset=page * limit, session=session
        )
        observations = await self.repository.observations(
            limit=limit + 1, offset=page * limit, session=session
        )
        return dict(
            actor_id=str(actor_id),
            as_of=utc(self.clock.now()).isoformat(),
            cases=cases[:limit],
            observations=observations[:limit],
            has_more=len(cases) > limit or len(observations) > limit,
            page=page,
        )

    async def _admin(self, command, principal, session):
        actor = await self.repository.actor(command.actor_id, session=session)
        require_current_principal(
            principal,
            command.actor_id,
            actor.user_id if actor else None,
            actor.telegram_id if actor else None,
            actor.max_id if actor else None,
        )
        if actor is None or actor.status != "active" or not actor.is_admin:
            raise PermissionError("repayment_active_admin_required")

    async def _replay(self, command, session):
        await self.repository.lock_operation(
            command.actor_id, command.operation_key, session=session
        )
        prior = await self.repository.command(
            command.actor_id, command.operation_key, session=session
        )
        if prior is not None:
            if prior["payload_hash"] != correction_payload_hash(command):
                raise ValueError("idempotency_payload_conflict")
            return prior["result"]
        return None

    async def _save(self, command, result, session):
        await self.repository.save_command(
            dict(
                command_id=command_id(command),
                actor_id=command.actor_id,
                operation_key=command.operation_key,
                action=type(command).__name__,
                payload_hash=correction_payload_hash(command),
                payload=asdict(command),
                result=result,
                recorded_at=utc(self.clock.now()),
            ),
            session=session,
        )
        return result

    async def observe(self, command, *, session, principal=None):
        await self._admin(command, principal, session)
        repo = self.ledger.repository
        await repo.lock_recipients(
            tuple(sorted({command.actor_id, command.recipient_id}, key=str)),
            session=session,
        )
        await self._admin(command, principal, session)
        previous = await self._replay(command, session)
        if previous is not None:
            return previous
        if (
            await self.repository.actor(command.recipient_id, session=session)
            is None
        ):
            raise ValueError("repayment_recipient_not_found")
        now = utc(self.clock.now())
        if command.occurred_at > now:
            raise ValueError("repayment_future_observation")
        observation_id = uuid5(command_id(command), "observation")
        claimed, blocker = False, None
        identity = None
        try:
            identity = self.physical_proofs.resolve_manual_identity(
                command.bank_account_label,
                command.bank_reference,
                direction="incoming",
            )
            await self.physical_proofs.claim(
                identity,
                PhysicalProofOwner(
                    producer="repayment",
                    intent_id=observation_id,
                    observation_id=observation_id,
                    command_id=command_id(command),
                ),
                session=session,
            )
            claimed = True
        except (PhysicalProofConflict, PhysicalProofUnavailable) as error:
            blocker = str(error)
        fact = asdict(command) | dict(
            observation_id=observation_id,
            command_id=command_id(command),
            proof_claimed=claimed,
            blocker=blocker,
            identity=asdict(identity) if identity else None,
            recorded_at=now,
        )
        await self.repository.append_observation(fact, session=session)
        return await self._save(
            command,
            dict(
                observation_id=str(observation_id),
                proof_claimed=claimed,
                blocker=blocker,
                applied=False,
            ),
            session,
        )

    async def apply(self, command, *, session, principal=None):
        await self._admin(command, principal, session)
        observation = await self.repository.observation(
            command.observation_id, session=session
        )
        original = await self.ledger.repository.get_issue(
            command.business_key, session=session
        )
        if observation is None or original is None:
            raise ValueError("repayment_source_required")
        basis = original.basis
        repo = self.ledger.repository
        await repo.lock_recipients(
            tuple(
                sorted(
                    {
                        command.actor_id,
                        basis.recipient_id,
                        observation["recipient_id"],
                    },
                    key=str,
                )
            ),
            session=session,
        )
        await self._admin(command, principal, session)
        await repo.lock_wallets(
            ((basis.recipient_id, basis.currency),), session=session
        )
        previous = await self._replay(command, session)
        if previous is not None:
            return previous
        if (
            await repo.get_issue(command.business_key, session=session)
            != original
            or await self.repository.observation(
                command.observation_id, session=session
            )
            != observation
        ):
            raise ValueError("repayment_scope_changed")
        if (
            observation["recipient_id"],
            observation["case_id"],
            observation["currency"],
        ) != (basis.recipient_id, command.case_id, basis.currency):
            raise ValueError("repayment_scope_mismatch")
        prior = await self.repository.application(
            command.observation_id, session=session
        )
        if prior is not None:
            if prior["result"]["business_key"] != command.business_key:
                raise ValueError("repayment_already_applied")
            return await self._save(command, prior["result"], session)
        originals = await self._locked_grounds(command, basis, session)
        return await self._apply_proven(
            command, originals, observation, session
        )

    async def _locked_grounds(self, command, basis, session):
        repo = self.ledger.repository
        grounds = await self.repository.case_grounds(
            command.case_id, basis.recipient_id, basis.currency, session=session
        )
        if command.business_key not in grounds:
            raise ValueError("repayment_scope_mismatch")
        originals = []
        for key in grounds:
            issued = await repo.get_issue(key, session=session)
            if issued is None:
                raise ValueError("repayment_original_issue_required")
            originals.append(issued)
        originals.sort(key=lambda issued: str(issued.obligation_id))
        for item_id in sorted(
            {issued.basis.paid_item_id for issued in originals}, key=str
        ):
            await repo.lock_item(item_id, session=session)
        if grounds != await self.repository.case_grounds(
            command.case_id, basis.recipient_id, basis.currency, session=session
        ):
            raise ValueError("repayment_scope_changed")
        return originals

    async def _apply_proven(self, command, originals, observation, session):
        repo = self.ledger.repository
        recipient_id, currency = (
            observation["recipient_id"],
            observation["currency"],
        )
        await self._proof(observation, session)
        await FinancialReconciliationService(repo).require_ready(
            recipient_id, currency, session=session
        )
        journal = await repo.list_for_recipient(
            recipient_id, currency, session=session
        )
        outstanding, newest_debt = self._case_balance(
            journal, originals, command.case_id, observation["recorded_at"]
        )
        total = sum(outstanding.values())
        if total != command.expected_debt_minor:
            raise ValueError("repayment_debt_version_conflict")
        amount = observation["amount_minor"]
        if amount > total:
            raise ValueError("repayment_exceeds_case_debt")
        now = utc(self.clock.now())
        if now < max(
            observation["recorded_at"], observation["occurred_at"], newest_debt
        ):
            raise ValueError("repayment_time_conflict")
        allocation = await self._allocate(
            originals, outstanding, amount, session
        )
        applications = [
            dict(
                application_id=str(
                    uuid5(
                        command_id(command),
                        "application:" + str(issued.obligation_id),
                    )
                ),
                obligation_id=str(issued.obligation_id),
                recovered_minor=portion,
            )
            for issued, portion, _ in allocation
        ]
        result = dict(
            application_id=applications[0]["application_id"],
            observation_id=str(command.observation_id),
            case_id=str(command.case_id),
            business_key=command.business_key,
            recovered_minor=amount,
            remaining_debt_minor=total - amount,
            applications=applications,
            applied=True,
        )
        for (issued, portion, source), application in zip(
            allocation, applications, strict=True
        ):
            movement = JournalMovement(
                obligation_id=issued.obligation_id,
                operation_key=f"repayment:{command.observation_id}:{issued.obligation_id}",
                event_id=str(command.observation_id),
                movement_type="recovery",
                amount_minor=portion,
                currency=currency,
                effective_at=now,
                recorded_at=now,
                actor_id=command.actor_id,
                actor_kind="admin",
                reason=command.reason,
                source_entry_id=source,
                case_id=command.case_id,
            )
            written = await repo.append(movement, session=session)
            await repo.apply_projection(written, session=session)
            await self.repository.append_application(
                dict(
                    application_id=UUID(application["application_id"]),
                    observation_id=command.observation_id,
                    command_id=command_id(command),
                    obligation_id=issued.obligation_id,
                    case_id=command.case_id,
                    recipient_id=recipient_id,
                    amount_minor=portion,
                    movement_id=await repo.get_entry_ref(
                        written.operation_key, session=session
                    ),
                    source_entry_id=source,
                    result=result,
                    recorded_at=now,
                ),
                session=session,
            )
        await FinancialReconciliationService(repo).require_ready(
            recipient_id, currency, session=session
        )
        return await self._save(command, result, session)

    @staticmethod
    def _case_balance(journal, originals, case_id, recorded_at):
        outstanding = dict.fromkeys(
            (issued.obligation_id for issued in originals), 0
        )
        newest_debt = recorded_at
        for entry in journal:
            if entry.obligation_id in outstanding and entry.case_id == case_id:
                if entry.movement_type == "debt":
                    outstanding[entry.obligation_id] += entry.amount_minor
                    newest_debt = max(newest_debt, entry.recorded_at)
                elif entry.movement_type == "recovery":
                    outstanding[entry.obligation_id] -= entry.amount_minor
        return outstanding, newest_debt

    async def _allocate(self, originals, outstanding, amount, session):
        repo = self.ledger.repository
        allocation, remaining = [], amount
        for issued in originals:
            portion = min(remaining, outstanding[issued.obligation_id])
            if portion <= 0:
                continue
            source = await repo.get_entry_ref(
                issued.movement.operation_key, session=session
            )
            if source is None:
                raise ValueError("repayment_original_issue_required")
            allocation.append((issued, portion, source))
            remaining -= portion
        return allocation

    async def _proof(self, observation, session):
        if not observation["proof_claimed"]:
            raise ValueError("repayment_physical_proof_required")
        identity = self.physical_proofs.resolve_manual_identity(
            observation["bank_account_label"],
            observation["bank_reference"],
            direction="incoming",
        )
        if asdict(identity) != observation["identity"]:
            raise ValueError("repayment_physical_proof_changed")
        await self.physical_proofs.lock(identity, session=session)
        owners = await self.physical_proofs.owners(identity, session=session)
        expected = PhysicalProofOwner(
            producer="repayment",
            intent_id=observation["observation_id"],
            observation_id=observation["observation_id"],
            command_id=observation["command_id"],
        )
        if owners != (expected,):
            raise ValueError("repayment_physical_proof_conflict")
