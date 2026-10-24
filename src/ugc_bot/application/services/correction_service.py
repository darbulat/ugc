"""Manual correction evidence; no refund money producer is installed."""

from dataclasses import asdict, replace
from uuid import UUID, uuid4

from ugc_bot.application.collaboration_ports import canonical
from ugc_bot.application.correction_ports import (
    CorrectionApplicationRefused,
    RecordManualRefundObservation,
    RequestSelectionRefund,
    ReviewSelectionRefund,
    correction_command_hash,
    correction_command_id,
)
from ugc_bot.application.native_principal_ports import require_current_principal
from ugc_bot.application.physical_proof_ports import (
    PhysicalProofConflict,
    PhysicalProofOwner,
    PhysicalProofUnavailable,
)
from ugc_bot.domain.corrections import (
    CorrectionEvent,
    CorrectionState,
    correction_payload_hash,
    require_text,
    require_uuid,
)
from ugc_bot.domain.financial import utc


def _require(value, code):
    if not value:
        raise ValueError(code)


class CorrectionService:
    def __init__(self, repository, physical_proofs, clock):
        self.repository = repository
        self.physical_proofs = physical_proofs
        self.clock = clock

    async def _authority(
        self, scope, principal, *, action, session, operation_key=None
    ):
        repo = self.repository
        await repo.prepare_users(scope, session=session)
        actor = await repo.actor(scope.actor_id, session=session)
        require_current_principal(
            principal,
            scope.actor_id,
            actor.user_id if actor else None,
            actor.telegram_id if actor else None,
            actor.max_id if actor else None,
        )
        _require(
            actor is not None
            and actor.status in ("active", "pause", "bot_blocked"),
            "correction_active_actor_required",
        )
        routing = await self._permission(
            scope, actor, action, operation_key, session=session
        )
        self._bindings(scope, routing)
        await repo.lock_prepared_scope(scope, session=session)
        await repo.load_scope(scope, session=session)
        return actor

    @staticmethod
    def _admin(actor):
        _require(
            actor.admin and actor.status == "active",
            "correction_active_admin_required",
        )

    @staticmethod
    def _own(scope, actor, client_id, current_client_id):
        _require(
            scope.client_id == actor.user_id
            and client_id == actor.user_id
            and current_client_id == actor.user_id,
            "correction_own_client_required",
        )

    async def _permission(
        self, scope, actor, action, operation_key, *, session
    ):
        if action == "admin" or (action == "preview" and actor.admin):
            self._admin(actor)
        routing = await self.repository.read_authority(
            scope, operation_key=operation_key, session=session
        )
        client_id = (
            routing.request_client_id
            if routing.request_client_id is not None
            else routing.case_client_id
        )
        if action == "own" or (action == "preview" and not actor.admin):
            self._own(
                scope,
                actor,
                client_id if client_id is not None else scope.client_id,
                routing.current_client_id,
            )
        elif action == "case":
            if actor.admin:
                self._admin(actor)
            else:
                self._own(scope, actor, client_id, routing.current_client_id)
        elif routing.action == "RequestSelectionRefund":
            self._own(scope, actor, client_id, routing.current_client_id)
        elif action == "operation" and routing.action is not None:
            self._admin(actor)
        return routing

    async def authorize_read(self, scope, *, action, session, principal):
        """UI reads share the complete current-native source barrier."""
        _require(
            action in ("context", "admin", "case", "preview"),
            "correction_read_action_invalid",
        )
        return await self._authority(
            scope, principal, action=action, session=session
        )

    @staticmethod
    def _bindings(scope, routing):
        request_clients = {
            routing.request_client_id,
            routing.current_client_id,
        } - {None}
        request_orders = {routing.request_order_id, scope.order_id} - {None}
        _require(
            len(request_clients) <= 1 and len(request_orders) <= 1,
            "correction_request_scope_invalid",
        )
        clients = {
            routing.case_client_id,
            routing.request_client_id,
            routing.current_client_id,
        } - {None}
        orders = {
            routing.case_order_id,
            routing.request_order_id,
            scope.order_id,
        } - {None}
        _require(
            len(clients) <= 1 and len(orders) <= 1,
            "correction_case_scope_invalid",
        )

    async def execute(self, command, *, session, principal=None):
        digest = correction_command_hash(command)
        repo = self.repository
        scope = await repo.discover_scope(command, session=session)
        await self._authority(
            scope,
            principal,
            action="own"
            if isinstance(command, RequestSelectionRefund)
            else "admin",
            session=session,
        )
        old = await repo.command(
            command.actor_id, command.operation_key, session=session
        )
        if old is not None:
            _require(
                old["payload_hash"] == digest, "idempotency_payload_conflict"
            )
            return old["result"]
        facts = await repo.facts(scope, session=session)
        state, consistent = (
            await repo.state_authority(scope.case_id, session=session)
            if scope.case_id
            else (None, True)
        )
        context = dict(
            scope=scope,
            facts=facts,
            state=state,
            consistent=consistent,
            command_id=correction_command_id(command),
            now=utc(self.clock.now()),
            session=session,
        )
        if isinstance(command, RequestSelectionRefund):
            result = await self._request(command, context)
        elif isinstance(command, ReviewSelectionRefund):
            result = await self._review(command, context)
        elif isinstance(command, RecordManualRefundObservation):
            result = await self._observe(command, context)
        else:
            result = await self._match(command, context)
        result = canonical(result)
        await repo.save_command(command, digest, result, session=session)
        return result

    @staticmethod
    def _refusal(scope, now):
        if not scope.available:
            return scope.unavailable_reason or "correction_source_unavailable"
        reason = scope.bundle.positive_a1_refusal(now)
        return "correction_" + reason if reason else None

    @staticmethod
    def _case(command, context):
        scope, facts = context["scope"], context["facts"]
        if scope.case_id:
            case = facts.one("cases")
            _require(
                case["case_id"] == str(scope.case_id),
                "correction_case_scope_invalid",
            )
            _require(
                case["order_id"] in (None, str(scope.order_id)),
                "correction_case_scope_invalid",
            )
            _require(
                case["client_id"] in (None, str(scope.client_id)),
                "correction_case_scope_invalid",
            )
            return scope.case_id
        return uuid4()

    async def _new_case(self, case_id, context):
        if context["scope"].case_id is None:
            await self.repository.append_fact(
                "cases",
                dict(
                    case_id=case_id,
                    command_id=context["command_id"],
                    client_id=context["scope"].client_id,
                    order_id=context["scope"].order_id,
                    recorded_at=context["now"],
                ),
                session=context["session"],
            )

    async def _event(self, command, context, case_id, source_id, **changes):
        old = context["state"]
        source_hash = context["scope"].source_hash or correction_payload_hash(
            ("manual_observation", command)
        )
        state = (
            replace(
                old, version=old.version + 1, source_hash=source_hash, **changes
            )
            if old
            else CorrectionState(
                case_id=case_id, version=1, source_hash=source_hash, **changes
            )
        )
        evidence = (
            getattr(command, "evidence_reference", None)
            or "correction:own-request"
        )
        evidence_hash = getattr(
            command, "evidence_hash", None
        ) or correction_command_hash(command)
        await self.repository.append_event(
            CorrectionEvent(
                event_id=uuid4(),
                case_id=case_id,
                version=state.version,
                command_id=context["command_id"],
                source_id=source_id,
                source_hash=source_hash,
                actor_id=command.actor_id,
                reason=command.reason,
                evidence_reference=evidence,
                evidence_hash=evidence_hash,
                recorded_at=context["now"],
                previous_state_hash=old.payload_hash if old else None,
                result_state=state,
                result_state_hash=state.payload_hash,
            ),
            session=context["session"],
        )
        return canonical(asdict(state))

    async def _request(self, command, c):
        _require(c["consistent"], "correction_state_unavailable")
        scope, facts = c["scope"], c["facts"]
        _require(scope.source_hash is not None, "correction_source_unavailable")
        _require(
            command.expected_source_hash == scope.source_hash,
            "correction_source_conflict",
        )
        _require(not facts.rows("requests"), "correction_request_exists")
        case, request = self._case(command, c), uuid4()
        await self._new_case(case, c)
        await self.repository.append_fact(
            "requests",
            dict(
                request_id=request,
                case_id=case,
                command_id=c["command_id"],
                order_id=scope.order_id,
                client_id=command.actor_id,
                paid_item_ids=canonical(command.paid_item_ids),
                source_hash=scope.source_hash,
                bundle=canonical(asdict(scope.bundle))["components"]
                if scope.bundle
                else None,
                recorded_at=c["now"],
            ),
            session=c["session"],
        )
        refusal = self._refusal(scope, c["now"])
        result = await self._event(
            command,
            c,
            case,
            request,
            request_status="requested",
            review_status="pending",
            blockers=(refusal,) if refusal else (),
        )
        return result | dict(request_id=request)

    def _fresh(self, command, c):
        self._case(command, c)
        state = c["state"]
        _require(
            c["consistent"] and state is not None,
            "correction_state_unavailable",
        )
        _require(
            command.expected_version == state.version,
            "correction_version_conflict",
        )
        _require(
            c["scope"].source_hash == command.expected_source_hash,
            "correction_source_conflict",
        )
        request = c["facts"].one("requests")
        scope = c["scope"]
        _require(
            request.get("case_id") == str(scope.case_id)
            and request.get("order_id") == str(scope.order_id)
            and request.get("client_id") == str(scope.client_id)
            and request.get("paid_item_ids")
            == canonical(scope.selected_paid_item_ids)
            and request.get("source_hash") == scope.source_hash
            and request.get("bundle")
            == (
                canonical(asdict(scope.bundle))["components"]
                if scope.bundle
                else None
            ),
            "correction_request_scope_invalid",
        )
        return request

    @staticmethod
    def _original(c):
        scope, facts = c["scope"], c["facts"]
        payment, invoice = facts.one("payments"), facts.one("invoice")
        payload = invoice.get("payload")
        _require(
            type(payload) is dict
            and invoice.get("event_id") == str(scope.intent_id)
            and invoice.get("event_type") == "financial.capture_intent"
            and scope.capture_id != scope.intent_id,
            "correction_original_payment_unavailable",
        )
        _require(
            payment.get("order_id") == str(scope.order_id)
            and payment.get("payment_id") == str(scope.payment_id)
            and payment.get("currency") == "RUB"
            and payment.get("status") == "paid"
            and payload.get("provider") == payment.get("provider"),
            "correction_original_payment_unavailable",
        )
        for value in (
            payload.get("account"),
            payment.get("provider"),
            payment.get("external_id"),
        ):
            _require(
                isinstance(value, str) and bool(value.strip()),
                "correction_original_payment_unavailable",
            )
        return payment

    async def _review(self, command, c):
        request = self._fresh(command, c)
        case = command.case_id
        if command.decision == "reject":
            return await self._event(
                command,
                c,
                case,
                UUID(request["request_id"]),
                review_status="rejected",
                blockers=c["state"].blockers,
            )
        refusal = self._refusal(c["scope"], c["now"])
        _require(not refusal, refusal or "correction_source_unavailable")
        self._request_receipt(c["facts"], request)
        intents = c["facts"].rows("intents")
        _require(len(intents) <= 1, "correction_intent_ambiguous")
        scope = c["scope"]
        capsule = self._source_capsule(c)
        intent = UUID(intents[0]["intent_id"]) if intents else uuid4()
        if intents:
            _require(
                intents[0].get("case_id") == str(case),
                "correction_approved_source_conflict",
            )
        else:
            await self._new_intent(intent, case, c)
        approval = uuid4()
        await self.repository.append_fact(
            "approvals",
            dict(
                approval_id=approval,
                intent_id=intent,
                case_id=case,
                command_id=c["command_id"],
                request_id=UUID(request["request_id"]),
                client_id=scope.client_id,
                order_id=scope.order_id,
                capture_id=scope.capture_id,
                payment_id=scope.payment_id,
                source_hash=scope.source_hash,
                source_capsule=capsule,
                bundle=canonical(asdict(scope.bundle))["components"],
                amount_minor=scope.bundle.total_minor,
                currency="RUB",
                review_version=c["state"].version + 1,
                recorded_at=c["now"],
            ),
            session=c["session"],
        )
        return (
            await self._event(
                command,
                c,
                case,
                approval,
                review_status="approved",
                blockers=(),
            )
        ) | dict(intent_id=intent, approval_id=approval)

    async def _new_intent(self, intent, case, c):
        await self.repository.append_fact(
            "intents",
            dict(
                intent_id=intent,
                case_id=case,
                command_id=c["command_id"],
                request_id=None,
                capture_id=None,
                payment_id=None,
                source_hash=None,
                bundle=None,
                amount_minor=None,
                currency=None,
                review_version=None,
                recorded_at=c["now"],
            ),
            session=c["session"],
        )

    def _source_capsule(self, c):
        scope = c["scope"]
        self._original(c)
        return canonical(
            dict(
                invoice=c["facts"].one("invoice"),
                payment=c["facts"].one("payments"),
                invoice_intent_id=scope.intent_id,
                capture_id=scope.capture_id,
                captured_at=scope.captured_at,
                quote_key=scope.quote_key,
                terms_reference=scope.terms_reference,
                ground_ids=scope.ground_ids,
                selected_paid_item_ids=scope.selected_paid_item_ids,
            )
        )

    @staticmethod
    def _request_receipt(facts, request):
        receipt = facts.one("commands", "command_id", request["command_id"])
        events = [
            row
            for row in facts.rows("events")
            if row.get("command_id") == request["command_id"]
            and row.get("source_id") == request["request_id"]
        ]
        _require(
            receipt.get("action") == "RequestSelectionRefund"
            and receipt.get("actor_id") == request.get("client_id")
            and receipt.get("result", {}).get("request_id")
            == request["request_id"]
            and len(events) == 1
            and events[0].get("actor_id") == request["client_id"]
            and events[0].get("case_id") == request["case_id"]
            and events[0].get("source_hash") == request["source_hash"]
            and all(
                receipt.get("result", {}).get(key) == value
                for key, value in events[0]["result_state"].items()
            ),
            "correction_request_scope_invalid",
        )

    async def _observe(self, command, c):
        case, observation_id = self._case(command, c), uuid4()
        await self._new_case(case, c)
        intents = c["facts"].rows("intents")
        _require(len(intents) <= 1, "correction_intent_ambiguous")
        intent = UUID(intents[0]["intent_id"]) if intents else uuid4()
        if not intents:
            await self._new_intent(intent, case, c)
        blockers = []
        try:
            identity = self.physical_proofs.resolve_manual_identity(
                command.bank_account_label,
                command.bank_reference,
                direction="outgoing",
            )
            await self.physical_proofs.claim(
                identity,
                PhysicalProofOwner(
                    producer="refund",
                    intent_id=intent,
                    observation_id=observation_id,
                    command_id=c["command_id"],
                ),
                session=c["session"],
            )
        except PhysicalProofConflict:
            blockers.append("correction_physical_proof_conflict")
        except PhysicalProofUnavailable:
            blockers.append("correction_physical_proof_unavailable")
        actual = {
            key: value
            for key, value in asdict(command).items()
            if key
            not in ("actor_id", "operation_key", "reason", "expected_version")
        }
        actual.update(
            observation_id=observation_id,
            intent_id=intent,
            case_id=case,
            command_id=c["command_id"],
            recorded_at=c["now"],
        )
        await self.repository.append_fact(
            "observations", actual, session=c["session"]
        )
        if not c["consistent"]:
            return dict(
                case_id=case,
                intent_id=intent,
                observation_id=observation_id,
                state_unavailable=True,
                blockers=tuple(blockers) + ("correction_state_unavailable",),
                applied=False,
            )
        if command.expected_version is not None and (
            c["state"] is None or command.expected_version != c["state"].version
        ):
            blockers.append("correction_version_conflict")
        if (
            command.reported_component != "selection"
            or type(command.amount_minor) is not int
            or command.amount_minor <= 0
            or command.currency != "RUB"
        ):
            blockers.append("correction_observation_economics_unavailable")
        if not c["scope"].available:
            blockers.append(c["scope"].unavailable_reason)
        observations = tuple(
            sorted(
                {
                    *(c["state"].observation_ids if c["state"] else ()),
                    observation_id,
                }
            )
        )
        result = await self._event(
            command,
            c,
            case,
            observation_id,
            observation_ids=observations,
            blockers=tuple(dict.fromkeys(blockers)),
        )
        return result | dict(
            intent_id=intent, observation_id=observation_id, applied=False
        )

    async def _verify_match(self, command, c):
        request = self._fresh(command, c)
        _require(
            c["state"].review_status == "approved",
            "correction_approved_review_required",
        )
        refusal = self._refusal(c["scope"], c["now"])
        _require(not refusal, refusal or "correction_source_unavailable")
        facts, scope = c["facts"], c["scope"]
        intent = facts.one("intents", "intent_id", command.intent_id)
        observation = facts.one(
            "observations", "observation_id", command.observation_id
        )
        authority = self._effective_approval(c, request, intent)
        payment = self._original(c)
        _require(
            observation["intent_id"] == intent["intent_id"]
            and observation["case_id"] == str(command.case_id)
            and observation["known_order_id"] in (None, str(scope.order_id))
            and observation["known_capture_intent_id"]
            in (None, str(scope.intent_id))
            and observation["original_payment_reference"]
            == payment["external_id"],
            "correction_observation_scope_conflict",
        )
        _require(
            observation["amount_minor"] == scope.bundle.total_minor
            and observation["currency"] == "RUB"
            and observation["reported_component"] == "selection",
            "correction_exact_bundle_required",
        )
        self._observation_receipt(facts, observation)
        try:
            key = self.physical_proofs.resolve_manual_identity(
                observation["bank_account_label"],
                observation["bank_reference"],
                direction="outgoing",
            )
            owners = await self.physical_proofs.owners(
                key, session=c["session"]
            )
            _require(
                bool(owners)
                and all(
                    (o.producer, o.intent_id) == ("refund", command.intent_id)
                    for o in owners
                ),
                "correction_physical_proof_conflict",
            )
            for owner in owners:
                original = facts.one(
                    "observations", "observation_id", owner.observation_id
                )
                self._observation_receipt(facts, original)
                original_key = self.physical_proofs.resolve_manual_identity(
                    original["bank_account_label"],
                    original["bank_reference"],
                    direction="outgoing",
                )
                _require(
                    original["intent_id"] == intent["intent_id"]
                    and original["case_id"] == str(command.case_id)
                    and original["command_id"] == str(owner.command_id)
                    and original_key == key,
                    "correction_physical_proof_unavailable",
                )
        except (PhysicalProofConflict, PhysicalProofUnavailable):
            raise ValueError("correction_physical_proof_unavailable") from None
        return authority

    def _effective_approval(self, c, request, intent):
        facts, scope = c["facts"], c["scope"]
        self._request_receipt(facts, request)
        self._match_links(facts, intent, request)
        commands = {row["command_id"]: row for row in facts.rows("commands")}
        reviews = [
            row
            for row in facts.rows("events")
            if commands.get(row.get("command_id"), {}).get("action")
            == "ReviewSelectionRefund"
        ]
        _require(bool(reviews), "correction_approved_review_required")
        approved = max(reviews, key=lambda row: row["version"])
        _require(
            approved.get("case_id") == str(scope.case_id)
            and approved.get("result_state", {}).get("review_status")
            == "approved"
            and approved.get("source_hash") == scope.source_hash,
            "correction_approved_review_required",
        )
        matching = [
            row
            for row in facts.rows("approvals")
            if row.get("approval_id") == approved.get("source_id")
        ]
        if matching:
            _require(len(matching) == 1, "correction_approved_review_required")
            authority = matching[0]
            _require(
                authority.get("intent_id") == intent["intent_id"]
                and authority.get("client_id") == str(scope.client_id)
                and authority.get("order_id") == str(scope.order_id)
                and authority.get("source_capsule") == self._source_capsule(c),
                "correction_approved_source_conflict",
            )
            approval_id = authority["approval_id"]
            require_uuid(UUID(approval_id))
        else:
            # Only genuine complete intent-linked old authority has no link.
            # Missing new-format authority cannot fall back.
            _require(
                approved.get("source_id") == intent["intent_id"]
                and not any(
                    row.get("intent_id") == intent["intent_id"]
                    for row in facts.rows("approvals")
                ),
                "correction_approved_review_required",
            )
            authority, approval_id = intent, None
        _require(
            authority.get("case_id") == str(scope.case_id)
            and authority.get("request_id") == request["request_id"]
            and authority.get("capture_id") == str(scope.capture_id)
            and authority.get("payment_id") == str(scope.payment_id)
            and authority.get("source_hash") == scope.source_hash
            and authority.get("bundle")
            == canonical(asdict(scope.bundle))["components"]
            and type(authority.get("amount_minor")) is int
            and authority["amount_minor"] == scope.bundle.total_minor
            and authority.get("currency") == "RUB"
            and type(authority.get("review_version")) is int
            and authority["review_version"] == approved["version"],
            "correction_approved_source_conflict",
        )
        _require(
            intent.get("case_id") == str(scope.case_id)
            and self._review_event(facts, authority, approval_id) == approved,
            "correction_approved_review_required",
        )
        return authority | dict(approval_id=approval_id)

    @staticmethod
    def _review_event(facts, authority, approval_id):
        source_id = approval_id or authority["intent_id"]
        events = [
            row
            for row in facts.rows("events")
            if row.get("case_id") == authority.get("case_id")
            and row.get("version") == authority.get("review_version")
            and row.get("source_id") == source_id
        ]
        _require(len(events) == 1, "correction_approved_review_required")
        event = events[0]
        receipt = facts.one("commands", "command_id", authority["command_id"])
        result = receipt.get("result", {})
        _require(
            receipt.get("action") == "ReviewSelectionRefund"
            and event.get("command_id") == receipt.get("command_id")
            and event.get("actor_id") == receipt.get("actor_id")
            and event.get("source_hash") == authority.get("source_hash")
            and event.get("recorded_at") == authority.get("recorded_at")
            and event.get("result_state", {}).get("review_status") == "approved"
            and result.get("intent_id") == authority.get("intent_id")
            and result.get("approval_id") == approval_id
            and all(
                result.get(key) == value
                for key, value in event["result_state"].items()
            ),
            "correction_approved_review_required",
        )
        return event

    def _match_links(self, facts, intent, request):
        """A present binding cannot be ignored in favor of legacy authority."""
        for approval in facts.rows("approvals"):
            _require(
                approval.get("request_id") == request["request_id"]
                and approval.get("case_id") == request["case_id"]
                and approval.get("order_id") == request["order_id"],
                "correction_match_approval_unavailable",
            )
            self._review_event(facts, approval, approval.get("approval_id"))
        for match in facts.rows("matches"):
            if match.get("intent_id") != intent["intent_id"]:
                continue
            _require(
                match.get("case_id") == request["case_id"]
                and match.get("order_id") == request["order_id"],
                "correction_match_approval_unavailable",
            )
            links = [
                row
                for row in facts.rows("match_approvals")
                if row.get("match_id") == match.get("match_id")
            ]
            receipt = facts.one("commands", "command_id", match["command_id"])
            result = receipt.get("result", {})
            events = [
                row
                for row in facts.rows("events")
                if row.get("command_id") == match["command_id"]
                and row.get("source_id") == match["match_id"]
            ]
            _require(
                receipt.get("action") == "MatchSelectionRefund"
                and result.get("match_id") == match["match_id"]
                and len(events) == 1
                and events[0].get("case_id") == match.get("case_id")
                and events[0].get("actor_id") == receipt.get("actor_id")
                and events[0].get("source_hash") == match.get("source_hash")
                and all(
                    result.get(key) == value
                    for key, value in events[0]["result_state"].items()
                ),
                "correction_match_approval_unavailable",
            )
            if not links:
                _require(
                    result.get("approval_id") is None
                    and intent.get("request_id") == request["request_id"]
                    and intent.get("case_id") == request["case_id"]
                    and all(
                        intent.get(key) == match.get(key)
                        for key in (
                            "case_id",
                            "capture_id",
                            "payment_id",
                            "source_hash",
                            "bundle",
                            "amount_minor",
                            "currency",
                            "review_version",
                        )
                    ),
                    "correction_match_approval_unavailable",
                )
                self._review_event(facts, intent, None)
                continue
            _require(len(links) == 1, "correction_match_approval_unavailable")
            approvals = [
                row
                for row in facts.rows("approvals")
                if row.get("approval_id") == links[0].get("approval_id")
            ]
            _require(
                len(approvals) == 1
                and result.get("approval_id") == links[0].get("approval_id")
                and all(
                    approvals[0].get(key) == match.get(key)
                    for key in (
                        "intent_id",
                        "case_id",
                        "capture_id",
                        "payment_id",
                        "source_hash",
                        "bundle",
                        "amount_minor",
                        "currency",
                        "review_version",
                    )
                ),
                "correction_match_approval_unavailable",
            )

    @staticmethod
    def _observation_receipt(facts, observation):
        receipt = facts.one("commands", "command_id", observation["command_id"])
        result = receipt.get("result", {})
        _require(
            receipt.get("action") == "RecordManualRefundObservation"
            and all(
                result.get(key) == observation.get(key)
                for key in ("observation_id", "intent_id", "case_id")
            ),
            "correction_physical_proof_unavailable",
        )

    async def _match(self, command, c):
        authority = await self._verify_match(command, c)
        scope, match_id = c["scope"], uuid4()
        row = dict(
            match_id=match_id,
            case_id=command.case_id,
            command_id=c["command_id"],
            intent_id=command.intent_id,
            observation_id=command.observation_id,
            order_id=scope.order_id,
            capture_id=scope.capture_id,
            payment_id=scope.payment_id,
            source_hash=scope.source_hash,
            bundle=canonical(asdict(scope.bundle))["components"],
            amount_minor=scope.bundle.total_minor,
            currency="RUB",
            review_version=authority["review_version"],
            recorded_at=c["now"],
        )
        try:
            async with self.repository.application_savepoint(
                session=c["session"]
            ):
                await self.repository.append_fact(
                    "matches", row, session=c["session"]
                )
                if authority["approval_id"] is not None:
                    await self.repository.append_fact(
                        "match_approvals",
                        dict(
                            match_id=match_id,
                            approval_id=UUID(authority["approval_id"]),
                        ),
                        session=c["session"],
                    )
        except CorrectionApplicationRefused:
            return await self._event(
                command,
                c,
                command.case_id,
                command.observation_id,
                application_status="unavailable",
                blockers=("correction_application_review_required",),
            )
        return (
            await self._event(
                command,
                c,
                command.case_id,
                match_id,
                match_status="matched",
                application_status="awaiting_assessment",
                blockers=("correction_compensation_assessment_required",),
            )
        ) | dict(
            match_id=match_id,
            applied=False,
            **(
                {"approval_id": authority["approval_id"]}
                if authority["approval_id"]
                else {}
            ),
        )

    async def get_for_actor(
        self, case_id, actor_id, *, session, principal=None
    ):
        require_uuid(case_id)
        require_uuid(actor_id)
        scope = await self.repository.discover_case_scope(
            actor_id, case_id, session=session
        )
        actor = await self._authority(
            scope, principal, action="case", session=session
        )
        facts = await self.repository.facts(scope, session=session)
        case = facts.one("cases")
        requests = facts.rows("requests")
        client = requests[0]["client_id"] if requests else case["client_id"]
        _require(
            actor.admin
            or (client == str(actor_id) and scope.client_id == actor_id),
            "correction_own_client_required",
        )
        state, valid = await self.repository.state_authority(
            case_id, session=session
        )
        result = dict(
            case_id=case_id,
            current=asdict(state) if state and valid else None,
            state_unavailable=not valid,
        )
        if actor.admin:
            result.update(
                observations=facts.rows("observations"),
                intents=facts.rows("intents"),
                matches=facts.rows("matches"),
            )
        return canonical(result)

    async def operation_for_actor(
        self, actor_id, operation_key, *, session, principal=None
    ):
        require_uuid(actor_id)
        require_text(operation_key, 256)
        scope = await self.repository.discover_operation_scope(
            actor_id, operation_key, session=session
        )
        actor = await self._authority(
            scope,
            principal,
            action="operation",
            operation_key=operation_key,
            session=session,
        )
        receipt = await self.repository.command(
            actor_id, operation_key, session=session
        )
        if receipt is None:
            return dict(recorded=False, original_result=None, current=None)
        if receipt["action"] == "RequestSelectionRefund":
            _require(
                scope.client_id == actor_id, "correction_own_client_required"
            )
        else:
            _require(
                actor.admin and actor.status == "active",
                "correction_active_admin_required",
            )
        state, valid = await self.repository.state_authority(
            UUID(receipt["result"]["case_id"]), session=session
        )
        return canonical(
            dict(
                recorded=True,
                original_result=receipt["result"],
                current=asdict(state) if state and valid else None,
                state_unavailable=not valid,
            )
        )
