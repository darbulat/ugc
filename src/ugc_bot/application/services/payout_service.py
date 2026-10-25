"""Available-only reservation and evidence-backed manual settlement; no I/O."""

import re
from datetime import timedelta
from uuid import UUID, uuid4

from ugc_bot.application.collaboration_ports import canonical
from ugc_bot.application.financial_ports import JournalMovement
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
    require_current_principal,
)
from ugc_bot.application.payout_contracts import (
    command_payload,
    document_input,
    field_definitions,
    owner_receipt,
    require_acceptance,
)
from ugc_bot.application.payout_errors import public_payout_code
from ugc_bot.application.payout_ports import (
    PublishPayoutRequirements,
    RecordPayoutResult,
    RequestPayout,
    ReviewPayout,
    StorePayoutRequisites,
    payout_payload_hash,
)
from ugc_bot.application.physical_proof_ports import (
    PhysicalProofConflict,
    PhysicalProofUnavailable,
)
from ugc_bot.domain.financial import MAX_MINOR, utc


def identity(value):
    try:
        value = UUID(str(value))
    except (ValueError, TypeError, AttributeError) as error:
        raise ValueError("payout_identity_invalid") from error
    if value.int == 0:
        raise ValueError("payout_identity_invalid")
    return value


def required(value, label, limit=4000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError("payout_" + label + "_required")
    return value.strip()


class PayoutService:
    def __init__(self, repository, work_guard, crypto, clock, config):
        (
            self.repository,
            self.work_guard,
            self.crypto,
            self.clock,
            self.config,
        ) = repository, work_guard, crypto, clock, config

    def _now(self):
        return utc(self.clock.now())

    def _crypto(self):
        if self.crypto is None:
            raise ValueError("payout_encryption_configuration_required")
        return self.crypto

    async def _actor(self, actor_id, *, admin=False, session, principal=None):
        actor = await self.repository.user(actor_id, session=session)
        require_current_principal(
            principal,
            actor_id,
            actor.get("user_id") if actor is not None else None,
            actor.get("telegram_id") if actor is not None else None,
            actor.get("max_id") if actor is not None else None,
        )
        if actor is None or actor["status"] not in (
            "active",
            "pause",
            "bot_blocked",
        ):
            raise ValueError("active_actor_required")
        if admin and (not actor["admin"] or actor["status"] != "active"):
            raise ValueError("active_admin_required")
        return actor

    async def execute(
        self,
        command,
        *,
        session,
        principal: AuthenticatedMessengerPrincipal | None = None,
    ):
        if (
            not self.config.core_enabled or not self.config.payouts_enabled
        ) and not isinstance(command, RecordPayoutResult):
            raise ValueError("financial_payouts_disabled")
        repo = self.repository
        actor = identity(command.actor_id)
        key = required(command.operation_key, "operation_key", 256)
        is_scope = isinstance(command, (ReviewPayout, RecordPayoutResult))
        request = (
            await repo.get(
                "requests", identity(command.request_id), session=session
            )
            if is_scope
            else None
        )
        recipient = request["recipient_id"] if request is not None else actor
        await repo.lock_users((actor, recipient), session=session)
        await self._actor(
            actor,
            admin=isinstance(
                command,
                (PublishPayoutRequirements, ReviewPayout, RecordPayoutResult),
            ),
            session=session,
            principal=principal,
        )
        if is_scope and request is None:
            raise ValueError("payout_not_found")
        payload = command_payload(command)
        action = (
            command.action
            if isinstance(command, ReviewPayout)
            else type(command).__name__
        )
        if isinstance(command, StorePayoutRequisites):
            payload["details"] = self._crypto().fingerprint(
                command.details, actor
            )
        if isinstance(command, RecordPayoutResult):
            # Command identity remains stable when its external key is absent.
            # Store this digest; raw recipient input never enters audit.
            payload["recipient_details"] = payout_payload_hash(
                command.recipient_details
            )
        digest = payout_payload_hash(canonical(payload))
        old = await repo.command(actor, key, session=session)
        if old is not None:
            if old["payload_hash"] != digest:
                raise ValueError("idempotency_payload_conflict")
            return old["result"]
        command_id = uuid4()
        result = await self._dispatch(
            command, request, recipient, command_id=command_id, session=session
        )
        result = canonical(result)
        await repo.add(
            "commands",
            dict(
                command_id=command_id,
                actor_id=actor,
                operation_key=key,
                action=action,
                payload_hash=digest,
                recorded_at=self._now(),
                result=result,
            ),
            session=session,
        )
        return result

    async def _dispatch(
        self, command, request, recipient, *, command_id, session
    ):
        repo = self.repository
        if isinstance(command, PublishPayoutRequirements):
            result = await self._publish(command, session=session)
        elif isinstance(command, StorePayoutRequisites):
            result = await self._store(command, session=session)
        elif isinstance(command, RequestPayout):
            result = await self._reserve(command, session=session)
        elif isinstance(command, (ReviewPayout, RecordPayoutResult)):
            assert request is not None
            rows = await repo.lock_money_scope(
                recipient, request["request_id"], session=session
            )
            state, consistent = await repo.state_authority(
                request["request_id"], session=session
            )
            if isinstance(command, RecordPayoutResult):
                result = await self._result(
                    command,
                    request,
                    state,
                    rows,
                    state_consistent=consistent and state is not None,
                    command_id=command_id,
                    session=session,
                )
            else:
                if not consistent or state is None:
                    raise ValueError("payout_state_reconciliation_required")
                result = await self._review(
                    command, request, state, rows, session=session
                )
        else:
            raise ValueError("payout_command_unknown")
        return result

    async def _publish(self, command, *, session):
        repo = self.repository
        await repo.requirements_lock(session=session)
        previous = await repo.latest_requirements(session=session)
        version = previous["version"] if previous is not None else 0
        if (
            type(command.expected_version) is not int
            or command.expected_version != version
        ):
            raise ValueError("payout_version_conflict")
        now, effective = self._now(), utc(command.effective_from)
        fields = tuple(command.required_fields)
        if (
            effective < now
            or len(fields) != len(set(fields))
            or not {"recipient_name", "bank_account", "legal_status"}
            <= set(fields)
            or len(fields) > 30
            or any(not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", f) for f in fields)
        ):
            raise ValueError("payout_requirements_invalid")
        record = dict(
            requirements_id=uuid4(),
            version=version + 1,
            actor_id=identity(command.actor_id),
            recorded_at=now,
            effective_from=effective,
            legal_reference=required(
                command.legal_reference, "legal_reference"
            ),
            terms_reference=required(
                command.terms_reference, "terms_reference"
            ),
            evidence_reference=required(
                command.evidence_reference, "evidence_reference"
            ),
            reason=required(command.reason, "reason"),
            required_fields=fields,
            enabled=command.enabled,
        )
        if type(command.enabled) is not bool:
            raise ValueError("payout_requirements_invalid")
        contract = None
        if (
            command.document is not None
            or command.field_definitions is not None
            or command.enabled
        ):
            if not await repo.contracts.available(session=session):
                raise ValueError("payout_readable_terms_required")
            source = document_input(command.document)
            if "document_id" in source:
                document = await repo.contracts.document(
                    source["document_id"], session=session
                )
            else:
                document = source | dict(
                    document_id=uuid4(),
                    publisher_id=identity(command.actor_id),
                    recorded_at=now,
                )
            definitions = field_definitions(
                command.field_definitions, fields, document["source_locale"]
            )
            contract = dict(document=document, field_definitions=definitions)
        await repo.add("requirements", record, session=session)
        if contract is not None:
            if "document_id" not in source:
                await repo.contracts.add("documents", document, session=session)
            await repo.contracts.add(
                "bindings",
                dict(
                    requirements_id=record["requirements_id"],
                    document_id=document["document_id"],
                    sha256=document["sha256"],
                    field_definitions=canonical(definitions),
                ),
                session=session,
            )
        return record | dict(
            document=contract["document"] if contract else None,
            field_definitions=contract["field_definitions"]
            if contract
            else None,
            readable=contract is not None,
        )

    async def _current_requirements(self, expected, *, session):
        await self.repository.requirements_lock(session=session)
        current = await self.repository.latest_requirements(
            self._now(), session=session
        )
        if current is None or not current["enabled"]:
            raise ValueError("published_payout_requirements_required")
        if current["requirements_id"] != identity(expected):
            raise ValueError("payout_requirements_changed")
        return current

    async def _store(self, command, *, session):
        current = await self._current_requirements(
            command.requirements_id, session=session
        )
        if command.accepted_terms_reference != current[
            "terms_reference"
        ] or set(command.details) != set(current["required_fields"]):
            raise ValueError("payout_accepted_terms_and_fields_required")
        contract = await self.repository.contracts.contract(
            current, session=session
        )
        require_acceptance(command, contract)
        actor, ref = identity(command.actor_id), uuid4()
        sealed = self._crypto().seal(command.details, actor, ref)
        await self.repository.add(
            "requisites",
            dict(
                requisites_id=ref,
                recipient_id=actor,
                requirements_id=current["requirements_id"],
                recorded_at=self._now(),
                **sealed,
            ),
            session=session,
        )
        document = contract["document"]
        await self.repository.contracts.add(
            "acceptances",
            dict(
                requisites_id=ref,
                recipient_id=actor,
                requirements_id=current["requirements_id"],
                document_id=document["document_id"],
                sha256=document["sha256"],
                accepted=True,
                accepted_at=self._now(),
            ),
            session=session,
        )
        return dict(
            requisites_id=ref,
            requirements_id=current["requirements_id"],
            masked_label=sealed["masked_label"],
            document_id=document["document_id"],
            document_hash=document["sha256"],
        )

    async def _clear(
        self,
        recipient,
        rows,
        *,
        requirements_id,
        matching=None,
        for_release=False,
        session,
    ):
        repo = self.repository
        if not for_release:
            await self._actor(recipient, session=session)
            await self._current_requirements(requirements_id, session=session)
        await repo.legacy_clear(recipient, session=session)
        replay = await repo.reconcile_locked(recipient, session=session)
        await repo.require_history_authority(recipient, session=session)
        if replay.balances["debt"] and not for_release:
            raise ValueError("payout_debt_manual_review_required")
        if await repo.unmatched_bank(recipient, matching, session=session):
            raise ValueError("payout_bank_reconciliation_required")
        release_check = (
            getattr(repo, "item_clear_for_release", None)
            if for_release
            else None
        )
        for row in rows:
            if release_check is not None:
                await release_check(row["paid_item_id"], session=session)
            else:
                await repo.item_clear(row["paid_item_id"], session=session)
            await self.work_guard.require_clear(
                row["paid_item_id"], session=session
            )
        return replay

    async def _reserve(self, command, *, session):
        if (
            type(command.amount_minor) is not int
            or not 0 < command.amount_minor <= MAX_MINOR
            or command.currency != "RUB"
        ):
            raise ValueError("payout_amount_invalid")
        repo, actor = self.repository, identity(command.actor_id)
        details = await repo.get(
            "requisites", identity(command.requisites_id), session=session
        )
        if details is None or details["recipient_id"] != actor:
            raise ValueError("payout_own_requisites_required")
        self._crypto().open(details, actor, details["requisites_id"])
        rows = await repo.lock_money_scope(actor, session=session)
        replay = await repo.reconcile_locked(actor, session=session)
        selected, remaining = [], command.amount_minor
        for row in rows:
            available = replay.by_obligation.get(row["id"], {}).get(
                "available", 0
            )
            if available and remaining:
                amount = min(remaining, available)
                selected.append((row, amount))
                remaining -= amount
        if remaining:
            raise ValueError("payout_available_insufficient")
        await self._clear(
            actor,
            [r for r, _ in selected],
            requirements_id=details["requirements_id"],
            session=session,
        )
        await repo.contracts.accepted_contract(details, session=session)
        now, ref = self._now(), uuid4()
        await repo.anchor(
            ref, actor, command.amount_minor, now, session=session
        )
        await repo.add(
            "requests",
            dict(
                request_id=ref,
                recipient_id=actor,
                amount_minor=command.amount_minor,
                currency="RUB",
                requisites_id=details["requisites_id"],
                requirements_id=details["requirements_id"],
                requested_at=now,
                deadline_at=now + timedelta(hours=72),
            ),
            session=session,
        )
        for row, amount in selected:
            allocation = dict(
                allocation_id=uuid4(),
                request_id=ref,
                obligation_id=row["id"],
                recipient_id=actor,
                amount_minor=amount,
                currency="RUB",
            )
            await repo.add("allocations", allocation, session=session)
            await self._movement(
                allocation,
                "available",
                "reserved",
                actor,
                "Owner requested payout reservation",
                now,
                session=session,
            )
        await repo.reconcile_locked(actor, session=session)
        return await repo.transition(
            ref,
            "reserved",
            actor,
            "request",
            "Owner requested available funds",
            now,
            session=session,
        )

    async def _movement(
        self,
        allocation,
        source,
        target,
        actor,
        reason,
        now,
        *,
        execution_id=None,
        case_id=None,
        session,
    ):
        movement = JournalMovement(
            obligation_id=allocation["obligation_id"],
            operation_key=f"payout:{allocation['allocation_id']}:{source}:{target}",
            event_id=f"payout:{allocation['request_id']}",
            movement_type="transfer",
            amount_minor=allocation["amount_minor"],
            currency="RUB",
            effective_at=now,
            recorded_at=now,
            actor_id=actor,
            actor_kind="user" if target == "reserved" else "admin",
            reason=reason,
            bucket_from=source,
            bucket_to=target,
            request_id=allocation["request_id"],
            allocation_id=allocation["allocation_id"],
            execution_id=execution_id,
            case_id=case_id,
        )
        await self.repository.movement_locked(movement, session=session)

    async def _safety_reason(
        self, request, rows, *, matching=None, for_release=False, session
    ):
        allocations = await self.repository.allocations(
            request["request_id"], session=session
        )
        selected = {a["obligation_id"] for a in allocations}
        try:
            await self._clear(
                request["recipient_id"],
                [r for r in rows if r["id"] in selected],
                requirements_id=request["requirements_id"],
                matching=matching,
                for_release=for_release,
                session=session,
            )
        except ValueError as error:
            return public_payout_code(error)
        return ""

    async def _review(self, command, request, state, rows, *, session):
        if (
            type(command.expected_version) is not int
            or command.expected_version != state["version"]
        ):
            raise ValueError("payout_version_conflict")
        reason = required(command.reason, "reason")
        repo, ref, actor, now = (
            self.repository,
            request["request_id"],
            identity(command.actor_id),
            self._now(),
        )
        if command.action == "escalate":
            return await self._escalate(
                request, state, actor, reason, now, session=session
            )
        if state["state"] in ("paid", "rejected", "executing", "unknown"):
            raise ValueError("payout_state_not_reviewable")
        block = await self._safety_reason(
            request,
            rows,
            for_release=command.action == "reject",
            session=session,
        )
        if block:
            return await repo.transition(
                ref,
                "blocked",
                actor,
                command.action,
                reason,
                now,
                block_reason=block,
                session=session,
            )
        allocations = await repo.allocations(ref, session=session)
        if command.action == "reject":
            for allocation in allocations:
                await self._movement(
                    allocation,
                    "reserved",
                    "available",
                    actor,
                    reason,
                    now,
                    session=session,
                )
            await repo.reconcile_locked(
                request["recipient_id"], session=session
            )
            return await repo.transition(
                ref, "rejected", actor, "reject", reason, now, session=session
            )
        required(command.evidence_reference, "evidence_reference")
        if command.action == "review":
            return await repo.transition(
                ref,
                "approved",
                actor,
                "review",
                reason,
                now,
                details={"evidence_reference": command.evidence_reference},
                session=session,
            )
        if command.action != "start" or state["state"] != "approved":
            raise ValueError("payout_review_approval_required")
        required(
            self.config.manual_bank_source_id, "bank_source_configuration", 256
        )
        details = await repo.get(
            "requisites", request["requisites_id"], session=session
        )
        self._crypto().open(
            details, request["recipient_id"], details["requisites_id"]
        )
        intent = dict(
            execution_id=uuid4(),
            request_id=ref,
            actor_id=actor,
            fence=uuid4(),
            amount_minor=request["amount_minor"],
            currency="RUB",
            fingerprint=details["fingerprint"],
            bank_account=required(
                self.config.manual_bank_account_id,
                "bank_account_configuration",
                256,
            ),
            prepared_at=now,
        )
        await repo.add("intents", intent, session=session)
        result = await repo.transition(
            ref,
            "executing",
            actor,
            "start",
            reason,
            now,
            execution_id=intent["execution_id"],
            details={"evidence_reference": command.evidence_reference},
            session=session,
        )
        return result | {"fence": str(intent["fence"])}

    async def _escalate(self, request, state, actor, reason, now, *, session):
        repo, ref = self.repository, request["request_id"]
        if now < request["deadline_at"] or state["state"] in (
            "paid",
            "rejected",
        ):
            raise ValueError("payout_sla_not_overdue")
        # Escalation is an audit event, never a bank decision or release.
        if await repo.event_exists(ref, "escalate", session=session):
            return await repo.view(ref, session=session)
        return await repo.transition(
            ref,
            state["state"],
            actor,
            "escalate",
            reason,
            now,
            block_reason=state["block_reason"],
            session=session,
        )

    async def _result(
        self,
        command,
        request,
        state,
        rows,
        *,
        state_consistent,
        command_id,
        session,
    ):
        repo, actor, now = (
            self.repository,
            identity(command.actor_id),
            self._now(),
        )
        reason = required(command.reason, "reason")
        evidence = required(command.evidence_reference, "evidence_reference")
        if (
            not isinstance(command.evidence_hash, str)
            or not re.fullmatch(r"[0-9a-f]{64}", command.evidence_hash)
            or command.status not in ("paid", "failed", "unknown")
        ):
            raise ValueError("payout_bank_evidence_invalid")
        intent = await repo.get(
            "intents", identity(command.execution_id), session=session
        )
        if intent is None or intent["request_id"] != request["request_id"]:
            raise ValueError("payout_execution_scope_invalid")
        outcome_id = uuid4()
        sealed = (
            self.crypto.seal(
                command.recipient_details or {"proof": "absent"},
                request["recipient_id"],
                outcome_id,
            )
            if self.crypto is not None
            else dict(
                ciphertext=b"", key_id="unavailable", fingerprint="0" * 64
            )
        )
        settled = (
            utc(command.settled_at) if command.settled_at is not None else None
        )
        # Own the recognized actual proof in the outer transaction before the
        # new observation enters history or the money savepoint can refuse it.
        proof_block = ""
        if (
            command.status == "paid"
            and command.bank_account.strip()
            and command.bank_reference.strip()
        ):
            try:
                await repo.claim_bank_reference(
                    command.bank_account.strip(),
                    command.bank_reference.strip(),
                    execution_id=intent["execution_id"],
                    outcome_id=outcome_id,
                    command_id=command_id,
                    session=session,
                )
            except PhysicalProofConflict:
                proof_block = "payout_bank_reference_reused"
            except PhysicalProofUnavailable:
                proof_block = "payout_bank_reconciliation_required"
        block = (
            await self._result_reason(
                command,
                request,
                state,
                rows,
                intent,
                sealed,
                settled,
                now,
                session=session,
            )
            if state_consistent
            else "payout_state_reconciliation_required"
        )
        block = (
            proof_block
            if proof_block == "payout_bank_reference_reused"
            else block or proof_block
        )
        applied = command.status == "paid" and not block
        outcome = dict(
            outcome_id=outcome_id,
            execution_id=intent["execution_id"],
            request_id=request["request_id"],
            actor_id=actor,
            status=command.status,
            amount_minor=command.amount_minor,
            currency=command.currency,
            settled_at=settled,
            bank_account=command.bank_account.strip(),
            bank_reference=command.bank_reference.strip(),
            evidence_reference=evidence,
            evidence_hash=command.evidence_hash,
            fingerprint=sealed["fingerprint"],
            key_id=sealed["key_id"],
            ciphertext=sealed["ciphertext"],
            recorded_at=now,
            applied=applied,
            review_reason=block,
        )
        if applied:
            try:
                async with repo.application_savepoint(session=session):
                    await repo.add("outcomes", outcome, session=session)
                    await self._settle(
                        request,
                        intent,
                        outcome_id,
                        command,
                        settled,
                        actor,
                        reason,
                        now,
                        session=session,
                    )
                    await repo.validate_movement_links(session=session)
            except ValueError:
                applied = False
                block = "payout_money_application_review_required"
                outcome = outcome | {"applied": False, "review_reason": block}
                await repo.add("outcomes", outcome, session=session)
        else:
            await repo.add("outcomes", outcome, session=session)
        if not state_consistent:
            # The immutable outcome is the audit fact. Do not append a false
            # state transition, trust a forged version, or repair projection.
            return dict(
                request_id=request["request_id"],
                state="unavailable",
                version=state["version"] if state is not None else None,
                outcome_id=outcome_id,
                applied=False,
                block_reason=block,
            )
        target = (
            "paid"
            if applied
            else (
                "unknown" if block or command.status == "unknown" else "failed"
            )
        )
        if state["state"] in ("paid", "rejected"):
            target = state["state"]
        return await repo.transition(
            request["request_id"],
            target,
            actor,
            "bank_result",
            reason,
            now,
            details={"outcome_id": outcome_id, "applied": applied},
            block_reason=block,
            session=session,
        )

    async def _settle(
        self,
        request,
        intent,
        outcome_id,
        command,
        settled,
        actor,
        reason,
        now,
        *,
        session,
    ):
        repo = self.repository
        await repo.add(
            "settlements",
            dict(
                execution_id=intent["execution_id"],
                request_id=request["request_id"],
                outcome_id=outcome_id,
                amount_minor=request["amount_minor"],
                currency="RUB",
                bank_account=command.bank_account.strip(),
                bank_reference=command.bank_reference.strip(),
                settled_at=settled,
            ),
            session=session,
        )
        for allocation in await repo.allocations(
            request["request_id"], session=session
        ):
            await self._movement(
                allocation,
                "reserved",
                "paid",
                actor,
                reason,
                now,
                execution_id=intent["execution_id"],
                session=session,
            )
        await repo.reconcile_locked(request["recipient_id"], session=session)

    async def _result_reason(
        self,
        command,
        request,
        state,
        rows,
        intent,
        sealed,
        settled,
        now,
        *,
        session,
    ):
        if not self.config.core_enabled or not self.config.payouts_enabled:
            return "financial_payouts_disabled"
        if self.crypto is None:
            return "payout_encryption_configuration_required"
        matching = dict(
            execution_id=intent["execution_id"],
            request_id=request["request_id"],
            amount_minor=command.amount_minor,
            currency=command.currency,
            settled_at=settled,
            bank_account=command.bank_account.strip(),
            bank_reference=command.bank_reference.strip(),
            fingerprint=sealed["fingerprint"],
        )
        block = await self._safety_reason(
            request, rows, matching=matching, session=session
        )
        if (
            command.expected_version != state["version"]
            or state["state"] not in ("executing", "unknown")
            or state["execution_id"] != intent["execution_id"]
            or str(command.fence) != str(intent["fence"])
        ):
            block = "payout_stale_execution"
        if command.status == "paid":
            if (
                command.amount_minor != request["amount_minor"]
                or command.currency != "RUB"
            ):
                block = "payout_bank_amount_or_currency_mismatch"
            elif command.bank_account.strip() != intent["bank_account"]:
                block = "payout_bank_account_mismatch"
            elif sealed["fingerprint"] != intent["fingerprint"]:
                block = "payout_bank_recipient_mismatch"
            elif (
                settled is None
                or not intent["prepared_at"] <= settled <= now
                or not command.bank_account.strip()
                or not command.bank_reference.strip()
            ):
                block = "payout_bank_settlement_proof_incomplete"
        return block

    async def get_for_actor(
        self,
        request_id,
        actor_id,
        *,
        session,
        principal: AuthenticatedMessengerPrincipal | None = None,
    ):
        actor_id, request_id = identity(actor_id), identity(request_id)
        await self.repository.lock_users((actor_id,), session=session)
        actor = await self._actor(
            actor_id, session=session, principal=principal
        )
        request = await self.repository.get(
            "requests", request_id, session=session
        )
        if (
            request is not None
            and request["recipient_id"] != actor_id
            and not (actor["admin"] and actor["status"] == "active")
        ):
            raise ValueError("payout_own_or_admin_required")
        return await self.repository.view(request_id, session=session)

    async def list_for_actor(
        self,
        actor_id,
        *,
        admin=False,
        session,
        principal: AuthenticatedMessengerPrincipal | None = None,
    ):
        actor_id = identity(actor_id)
        await self.repository.lock_users((actor_id,), session=session)
        await self._actor(
            actor_id, admin=admin, session=session, principal=principal
        )
        return tuple(
            [
                await self.repository.view(ref, session=session)
                for ref in await self.repository.list_requests(
                    None if admin else actor_id, session=session
                )
            ]
        )

    async def requirements_for_actor(
        self,
        actor_id,
        *,
        session,
        principal: AuthenticatedMessengerPrincipal | None = None,
    ):
        actor_id = identity(actor_id)
        await self.repository.lock_users((actor_id,), session=session)
        await self._actor(actor_id, session=session, principal=principal)
        result = await self.repository.latest_requirements(
            self._now(), session=session
        )
        public = (
            "requirements_id",
            "version",
            "effective_from",
            "terms_reference",
            "required_fields",
            "enabled",
        )
        if result is None:
            return None
        contract = await self.repository.contracts.contract(
            result, session=session
        )
        return canonical(
            {key: result[key] for key in public}
            | dict(
                document=contract["document"] if contract else None,
                field_definitions=contract["field_definitions"]
                if contract
                else None,
                readable=contract is not None,
                unavailable_reason=""
                if contract
                else "payout_readable_terms_required",
            )
        )

    async def reveal_for_admin(
        self,
        request_id,
        actor_id,
        *,
        operation_key,
        reason,
        session,
        principal: AuthenticatedMessengerPrincipal | None = None,
    ):
        actor_id, request_id = identity(actor_id), identity(request_id)
        request = await self.repository.get(
            "requests", request_id, session=session
        )
        await self.repository.lock_users(
            (
                actor_id,
                request["recipient_id"] if request is not None else actor_id,
            ),
            session=session,
        )
        await self._actor(
            actor_id, admin=True, session=session, principal=principal
        )
        if request is None:
            raise ValueError("payout_not_found")
        key = required(operation_key, "operation_key", 256)
        proof = dict(
            request_id=str(request_id), reason=required(reason, "reason")
        )
        old = await self.repository.command(actor_id, key, session=session)
        digest = payout_payload_hash(proof)
        if old is not None and old["payload_hash"] != digest:
            raise ValueError("idempotency_payload_conflict")
        if old is None:
            await self.repository.add(
                "commands",
                dict(
                    command_id=uuid4(),
                    actor_id=actor_id,
                    operation_key=key,
                    action="requisites_revealed",
                    payload_hash=digest,
                    recorded_at=self._now(),
                    result=proof,
                ),
                session=session,
            )
        details = await self.repository.get(
            "requisites", request["requisites_id"], session=session
        )
        return self._crypto().open(
            details, request["recipient_id"], details["requisites_id"]
        )

    async def requirements_for_admin(
        self,
        actor_id,
        *,
        session,
        principal: AuthenticatedMessengerPrincipal | None = None,
    ):
        actor_id = identity(actor_id)
        await self.repository.lock_users((actor_id,), session=session)
        await self._actor(
            actor_id, admin=True, session=session, principal=principal
        )
        values = []
        for row in await self.repository.list_requirements(session=session):
            contract = await self.repository.contracts.contract(
                row, session=session
            )
            values.append(
                canonical(
                    dict(row)
                    | dict(
                        document=contract["document"] if contract else None,
                        field_definitions=(
                            contract["field_definitions"] if contract else None
                        ),
                        readable=contract is not None,
                    )
                )
            )
        return tuple(values)

    async def history_for_admin(
        self,
        request_id,
        actor_id,
        *,
        session,
        principal: AuthenticatedMessengerPrincipal | None = None,
    ):
        actor_id, request_id = identity(actor_id), identity(request_id)
        await self.repository.lock_users((actor_id,), session=session)
        await self._actor(
            actor_id, admin=True, session=session, principal=principal
        )
        if (
            await self.repository.get("requests", request_id, session=session)
            is None
        ):
            return None
        result = {}
        for name in ("events", "intents", "outcomes", "settlements"):
            values = await self.repository.list_facts(
                name, request_id, session=session
            )
            result[name] = [
                canonical(
                    {
                        key: value
                        for key, value in row.items()
                        if key not in ("ciphertext", "fingerprint", "key_id")
                    }
                )
                for row in values
            ]
        return result

    async def operation_for_actor(
        self,
        actor_id,
        operation_key,
        *,
        session,
        principal: AuthenticatedMessengerPrincipal | None = None,
    ):
        actor_id = identity(actor_id)
        key = required(operation_key, "operation_key", 256)
        await self.repository.lock_users((actor_id,), session=session)
        await self._actor(actor_id, session=session, principal=principal)
        receipt = await self.repository.command(actor_id, key, session=session)
        observed = self._now()
        if receipt is None:
            return canonical(dict(recorded=False, observed_at=observed))
        result = owner_receipt(receipt["action"], receipt["result"])
        kind = (
            "requests" if receipt["action"] == "RequestPayout" else "requisites"
        )
        ref = identity(
            result["request_id"]
            if kind == "requests"
            else result["requisites_id"]
        )
        resource = await self.repository.get(kind, ref, session=session)
        if (
            resource is None
            or resource["recipient_id"] != actor_id
            or str(resource["requirements_id"]) != result["requirements_id"]
        ):
            raise ValueError("payout_operation_unavailable")
        return canonical(
            dict(
                recorded=True,
                action=receipt["action"],
                result=result,
                recorded_at=receipt["recorded_at"],
                observed_at=observed,
            )
        )

    async def requisites_for_actor(
        self,
        actor_id,
        *,
        session,
        principal: AuthenticatedMessengerPrincipal | None = None,
    ):
        actor_id = identity(actor_id)
        repo = self.repository
        await repo.lock_users((actor_id,), session=session)
        await self._actor(actor_id, session=session, principal=principal)
        await repo.requirements_lock(session=session)
        current = await repo.latest_requirements(self._now(), session=session)
        values = []
        for row in await repo.contracts.own_requisites(
            actor_id, session=session
        ):
            reasons = []
            if not self.config.core_enabled or not self.config.payouts_enabled:
                reasons.append("financial_payouts_disabled")
            if (
                current is None
                or not current["enabled"]
                or current["requirements_id"] != row["requirements_id"]
            ):
                reasons.append("payout_requirements_changed")
            contract = None
            try:
                contract = await repo.contracts.accepted_contract(
                    row, session=session
                )
            except ValueError as error:
                reasons.append(public_payout_code(error))
            if self.crypto is None:
                reasons.append("payout_encryption_configuration_required")
            else:
                try:
                    self.crypto.open(row, actor_id, row["requisites_id"])
                except ValueError:
                    reasons.append("payout_requisites_authentication_failed")
            document = contract["document"] if contract else None
            values.append(
                dict(
                    requisites_id=row["requisites_id"],
                    requirements_id=row["requirements_id"],
                    requirements_version=row["requirements_version"],
                    document_id=document["document_id"] if document else None,
                    document_hash=document["sha256"] if document else None,
                    recorded_at=row["recorded_at"],
                    masked_label=row["masked_label"],
                    usable=not reasons,
                    unusable_reasons=reasons,
                )
            )
        return canonical(values)
