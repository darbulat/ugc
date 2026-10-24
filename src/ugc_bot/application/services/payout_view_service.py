"""Conservative snapshot hints and bounded payout DTOs."""

import re
from dataclasses import dataclass

from ugc_bot.application.collaboration_ports import canonical
from ugc_bot.application.payout_errors import (
    PUBLIC_PAYOUT_BLOCK_CODES,
)
from ugc_bot.application.payout_view_ports import (
    Cursor,
    Page,
    PayoutReadNotFound,
    PayoutReadPrincipal,
    cursor_decode,
    cursor_encode,
)
from ugc_bot.application.services.financial_reconciliation_service import (
    BUCKETS,
    replay_journal,
    validate_issuance,
)
from ugc_bot.domain.financial import MAX_MINOR, utc
from ugc_bot.miniapp.payout_wire import payout_to_wire

DEFAULT_PAGE = Page()

READ_CODES = (
    frozenset(
        {
            "payout_source_unavailable",
            "payout_source_integrity_required",
            "payout_wallet_missing",
            "payout_requisites_unavailable",
            "payout_read_identity_invalid",
            "payout_allocation_source_unavailable",
            "payout_observation_source_unavailable",
            "payout_recipient_unavailable",
            "payout_available_insufficient",
            "payout_requirements_unreadable",
            "retained_version_required",
        }
    )
    | PUBLIC_PAYOUT_BLOCK_CODES
)


def blockers(values):
    return list(
        dict.fromkeys(
            v if v in READ_CODES else "payout_source_integrity_required"
            for v in values
            if v
        )
    )


def mask(value):
    return (
        value
        if isinstance(value, str) and re.fullmatch(r"••••[\s\S]{0,4}", value)
        else None
    )


@dataclass(frozen=True, slots=True)
class Money:
    state: str
    balances: dict | None
    by_obligation: dict
    blockers: tuple[str, ...]


def money(facts, recipient_id):
    if facts.source_blockers:
        return Money(
            "unavailable", None, {}, tuple(blockers(facts.source_blockers))
        )
    if not facts.obligations and not facts.movements and facts.wallet is None:
        return Money("known_empty", dict.fromkeys(BUCKETS, 0), {}, ())
    if facts.wallet is None:
        return Money("unavailable", None, {}, ("payout_wallet_missing",))
    try:
        replay = replay_journal(facts.movements, currency="RUB")
        errors = validate_issuance(
            facts.movements,
            tuple(o.basis for o in facts.obligations),
            recipient_id=recipient_id,
            currency="RUB",
        )
        if (
            not replay.balanced
            or errors
            or dict(facts.wallet) != replay.balances
        ):
            raise ValueError()
    except (ValueError, KeyError, TypeError, AttributeError):
        return Money(
            "unavailable", None, {}, ("reconciliation_mismatch_audit_required",)
        )
    return Money("ready", replay.balances, replay.by_obligation, ())


def requirement(row, *, admin=False):
    if row is None:
        return None
    keys = {
        "requirements_id",
        "version",
        "effective_from",
        "terms_reference",
        "required_fields",
        "enabled",
        "document",
        "field_definitions",
        "readable",
    }
    if admin:
        keys |= {
            "actor_id",
            "recorded_at",
            "legal_reference",
            "evidence_reference",
            "reason",
        }
    result = {
        k: row[k]
        for k in keys
        if k in row and k not in ("document", "field_definitions")
    }
    document = row.get("document")
    result["document"] = (
        {
            k: document[k]
            for k in (
                "document_id",
                "content_text",
                "source_locale",
                "sha256",
                "publisher_id",
                "recorded_at",
            )
            if k in document
        }
        if isinstance(document, dict)
        else None
    )
    definitions = row.get("field_definitions")
    result["field_definitions"] = (
        [
            {
                k: d[k]
                for k in ("key", "labels", "help", "allowed_values")
                if k in d
            }
            for d in definitions
            if isinstance(d, dict)
        ]
        if isinstance(definitions, (list, tuple))
        else None
    )
    return result


class PayoutViewService:
    def __init__(self, repository, clock, config, crypto):
        self.repository, self.clock, self.config, self.crypto = (
            repository,
            clock,
            config,
            crypto,
        )

    def _at(self):
        return utc(self.clock.now())

    async def _actor(self, reader, principal, *, admin=False):
        actor = await reader.actor(principal)
        if (
            actor is None
            or (actor.actor_id, actor.platform, actor.external_id)
            != (principal.actor_id, principal.platform, principal.external_id)
            or actor.status not in ("active", "pause", "bot_blocked")
            or (admin and (not actor.admin or actor.status != "active"))
        ):
            raise PermissionError("payout_read_forbidden")
        return actor

    def _flags(self):
        return (
            []
            if self.config.core_enabled and self.config.payouts_enabled
            else ["financial_payouts_disabled"]
        )

    def _recipient_blockers(self, facts, amounts):
        values = list(amounts.blockers) + list(facts.readiness_blockers)
        if facts.recipient_status not in ("active", "pause", "bot_blocked"):
            values.append("payout_recipient_unavailable")
        if amounts.balances and amounts.balances["debt"]:
            values.append("payout_debt_manual_review_required")
        return blockers(values)

    def _requirements_blockers(self, requirements):
        current = requirements.current
        values = list(requirements.source_blockers)
        if not current or not current.get("enabled"):
            values.append("published_payout_requirements_required")
        elif not current.get("readable"):
            values.append("payout_readable_terms_required")
        return blockers(values)

    def _authenticate(self, requisite, recipient_id):
        if requisite is None:
            return ["payout_requisites_unavailable"]
        if self.crypto is None:
            return ["payout_encryption_configuration_required"]
        try:
            self.crypto.open(
                requisite.row, recipient_id, requisite.row["requisites_id"]
            )
        except ValueError:
            return ["payout_requisites_authentication_failed"]
        return []

    def _masked(self, requisite, current, recipient_id):
        row = requisite.row
        errors = (
            self._flags()
            + list(requisite.source_blockers)
            + self._authenticate(requisite, recipient_id)
        )
        if (
            not current
            or not current.get("enabled")
            or current["requirements_id"] != row["requirements_id"]
        ):
            errors.append("payout_requirements_changed")
        if requisite.contract is None or not requisite.accepted:
            errors.append("payout_readable_acceptance_required")
        document = (
            requisite.contract.get("document") if requisite.contract else None
        )
        safe_mask = mask(row.get("masked_label"))
        if safe_mask is None:
            errors.append("payout_source_integrity_required")
        return dict(
            requisites_id=row["requisites_id"],
            requirements_id=row["requirements_id"],
            requirements_version=row.get("requirements_version"),
            recorded_at=row["recorded_at"],
            masked_label=safe_mask,
            document_id=document["document_id"] if document else None,
            document_hash=document["sha256"] if document else None,
            usable=not errors,
            unusable_reasons=blockers(errors),
        )

    def _page(
        self,
        rows,
        page,
        principal,
        route,
        *,
        scope=None,
        position="recorded_at",
        identity="requisites_id",
        render=lambda row: row,
    ):
        selected = rows[: page.limit]
        more = len(rows) > page.limit
        last = selected[-1] if selected else None
        raw = last.row if hasattr(last, "row") else last
        cursor = (
            cursor_encode(
                Cursor(raw[position], raw[identity]), principal, route, scope
            )
            if more and raw is not None
            else None
        )
        return dict(
            entries=[render(row) for row in selected],
            has_more=more,
            next_cursor=cursor,
        )

    async def context(self, principal, *, page=DEFAULT_PAGE):
        async with self.repository.snapshot() as reader:
            actor = await self._actor(reader, principal)
            at = self._at()
            cursor = cursor_decode(page.cursor, principal, "masked")
            financial = await reader.financial(actor.actor_id)
            amounts = money(financial, actor.actor_id)
            requirements = await reader.requirements(at)
            recipient = self._recipient_blockers(financial, amounts)
            base = (
                self._flags()
                + recipient
                + self._requirements_blockers(requirements)
            )
            if self.crypto is None:
                base.append("payout_encryption_configuration_required")
            masked = self._page(
                await reader.requisites(actor.actor_id, page, cursor),
                page,
                principal,
                "masked",
                render=lambda row: self._masked(
                    row, requirements.current, actor.actor_id
                ),
            )
            admin = actor.admin and actor.status == "active"
            store_sources = await reader.command_blockers("store")
            publication_sources = (
                await reader.command_blockers("publish") if admin else ()
            )
            return payout_to_wire(
                canonical(
                    dict(
                        actor_id=actor.actor_id,
                        as_of=at,
                        account_status=actor.status,
                        admin=admin,
                        writes_paused=bool(self._flags()),
                        financial=dict(
                            state=amounts.state,
                            currency="RUB",
                            balances={
                                b + "_minor": v
                                for b, v in amounts.balances.items()
                            }
                            if amounts.balances is not None
                            else None,
                        ),
                        recipient_blockers=recipient,
                        requirements=requirement(requirements.current),
                        latest_publication=requirement(
                            requirements.latest, admin=True
                        )
                        if admin
                        else None,
                        masked_requisites=masked,
                        capabilities=dict(
                            begin_request=not base
                            and bool(
                                amounts.balances
                                and amounts.balances["available"] > 0
                            ),
                            store_requisites=not (
                                self._flags()
                                + self._requirements_blockers(requirements)
                                + list(store_sources)
                            )
                            and self.crypto is not None,
                            read_own_requests=True,
                            read_admin_queue=admin,
                            read_admin_requirements=admin,
                            publish_requirements=admin
                            and not (
                                self._flags()
                                or requirements.source_blockers
                                or publication_sources
                            ),
                        ),
                        blockers=blockers(base),
                    )
                )
            )

    async def reserve_preview(
        self, principal, requisites_id, amount_minor, *, currency="RUB"
    ):
        if (
            type(amount_minor) is not int
            or not 0 < amount_minor <= MAX_MINOR
            or currency != "RUB"
        ):
            raise ValueError("payout_amount_invalid")
        async with self.repository.snapshot() as reader:
            actor = await self._actor(reader, principal)
            at = self._at()
            facts = await reader.financial(actor.actor_id)
            amounts = money(facts, actor.actor_id)
            requirements = await reader.requirements(at)
            requisite = await reader.requisite(actor.actor_id, requisites_id)
            errors = (
                self._flags()
                + self._recipient_blockers(facts, amounts)
                + self._requirements_blockers(requirements)
            )
            if requisite is None:
                errors.append("payout_requisites_unavailable")
            else:
                masked = self._masked(
                    requisite, requirements.current, actor.actor_id
                )
                errors += masked["unusable_reasons"]
            remaining = amount_minor
            selected = []
            for obligation in sorted(
                facts.obligations, key=lambda o: o.basis.obligation_id
            ):
                available = amounts.by_obligation.get(
                    obligation.basis.obligation_id, {}
                ).get("available", 0)
                if available > 0 and remaining:
                    selected.append(obligation.paid_item_id)
                    remaining -= min(remaining, available)
            if remaining:
                errors.append("payout_available_insufficient")
            else:
                errors += list(
                    await reader.item_blockers(tuple(dict.fromkeys(selected)))
                )
            errors = blockers(errors)
            return canonical(
                dict(
                    as_of=at,
                    amount_minor=str(amount_minor),
                    currency="RUB",
                    can_reserve=not errors,
                    blockers=errors,
                )
            )

    def _authority(self, fact):
        proof = fact.authority
        if (
            not fact.consistent
            or proof is None
            or proof.get("request_id") != fact.row["request_id"]
            or type(proof.get("version")) is not int
            or proof["version"] < 1
            or proof.get("state")
            not in (
                "reserved",
                "approved",
                "blocked",
                "executing",
                "unknown",
                "failed",
                "paid",
                "rejected",
            )
            or proof.get("block_reason") not in PUBLIC_PAYOUT_BLOCK_CODES
        ):
            return None
        return proof

    def _request_view(self, fact, at):
        row = fact.row
        proof = self._authority(fact)
        return dict(
            request_id=row["request_id"],
            amount_minor=row["amount_minor"],
            currency=row["currency"],
            requisites_id=row["requisites_id"],
            requirements_id=row["requirements_id"],
            requested_at=row["requested_at"],
            deadline_at=row["deadline_at"],
            overdue=at >= row["deadline_at"],
            masked_label=mask(fact.requisites.row.get("masked_label"))
            if fact.requisites
            else None,
            state=proof["state"] if proof else "unavailable",
            version=proof["version"] if proof else None,
            execution_id=proof["execution_id"] if proof else None,
            block_reason=proof["block_reason"]
            if proof
            else "payout_state_reconciliation_required",
            as_of=at,
            allowed_actions=[],
        )

    def _intent(self, value, fact):
        proof = self._authority(fact)
        version = proof["version"] if proof else value.get("version")
        provenance = (
            "current_authority"
            if proof
            else value.get("version_provenance")
            if version is not None
            else "retained_version_required"
        )
        return dict(
            execution_id=value["execution_id"],
            fence=value["fence"],
            bank_account=value["bank_account"],
            prepared_at=value["prepared_at"],
            amount_minor=value["amount_minor"],
            currency=value["currency"],
            expected_version=version,
            version_provenance=provenance,
        )

    async def _request_safety(self, reader, fact, at, *, release):
        row = fact.row
        facts = await reader.financial(row["recipient_id"])
        amounts = money(facts, row["recipient_id"])
        errors = (
            list(amounts.blockers)
            + list(fact.source_blockers)
            + list(facts.readiness_blockers)
        )
        if release:
            errors = [
                e
                for e in errors
                if e
                not in (
                    "payout_debt_manual_review_required",
                    "payout_recipient_unavailable",
                    "payout_requirements_changed",
                )
            ]
        else:
            if facts.recipient_status not in ("active", "pause", "bot_blocked"):
                errors.append("payout_recipient_unavailable")
            if amounts.balances and amounts.balances["debt"]:
                errors.append("payout_debt_manual_review_required")
            current = (await reader.requirements(at)).current
            if current is None or not current.get("enabled"):
                errors.append("published_payout_requirements_required")
            elif current["requirements_id"] != row["requirements_id"]:
                errors.append("payout_requirements_changed")
        by_id = {o.basis.obligation_id: o for o in facts.obligations}
        if (
            not fact.allocations
            or sum(a.amount_minor for a in fact.allocations)
            != row["amount_minor"]
            or any(
                a.obligation_id not in by_id
                or by_id[a.obligation_id].paid_item_id != a.paid_item_id
                for a in fact.allocations
            )
        ):
            errors.append("payout_allocation_source_unavailable")
        else:
            errors += list(
                await reader.item_blockers(
                    tuple(
                        dict.fromkeys(a.paid_item_id for a in fact.allocations)
                    )
                )
            )
        return blockers(errors)

    async def _detail(self, reader, actor, fact, at):
        result = self._request_view(fact, at)
        if not actor.admin or actor.status != "active":
            return result
        proof = self._authority(fact)
        actions = []
        action_blockers = {}
        if self._authenticate(fact.requisites, fact.row["recipient_id"]):
            action_blockers["reveal_requisites"] = self._authenticate(
                fact.requisites, fact.row["recipient_id"]
            )
        else:
            actions.append("reveal_requisites")
        if fact.observation_ready and fact.retained_intents:
            actions.append("record_observation")
        else:
            action_blockers["record_observation"] = blockers(
                fact.observation_blockers or ["payout_execution_scope_invalid"]
            )
        current = fact.current_intent
        if (
            not proof
            or not current
            or proof["execution_id"] != current["execution_id"]
        ):
            current = None
        result["current_execution"] = (
            self._intent(current, fact) if current else None
        )
        result["observation"] = dict(
            can_record="record_observation" in actions,
            retained_intents=dict(
                entries=[self._intent(v, fact) for v in fact.retained_intents],
                has_more=fact.more_intents,
                next_cursor=cursor_encode(
                    Cursor(
                        fact.retained_intents[-1]["prepared_at"],
                        fact.retained_intents[-1]["execution_id"],
                    ),
                    PayoutReadPrincipal(
                        actor.actor_id, actor.platform, actor.external_id
                    ),
                    "history:intents",
                    fact.row["request_id"],
                )
                if fact.more_intents and fact.retained_intents
                else None,
            ),
        )
        ordinary, denials = await self._ordinary_actions(reader, fact, at)
        actions += ordinary
        action_blockers.update(denials)
        result["allowed_actions"] = actions
        result["action_blockers"] = action_blockers
        return result

    async def _ordinary_actions(self, reader, fact, at):
        proof = self._authority(fact)
        physical = await reader.command_blockers("review")
        if not proof or self._flags() or physical:
            return [], {
                "ordinary": self._flags()
                or list(physical)
                or ["payout_state_reconciliation_required"]
            }
        actions = []
        denials = {}
        state = proof["state"]
        if (
            state not in ("paid", "rejected")
            and at >= fact.row["deadline_at"]
            and not fact.escalated
        ):
            actions.append("escalate")
        if state in ("paid", "rejected", "executing", "unknown"):
            return actions, denials
        ordinary = await self._request_safety(reader, fact, at, release=False)
        release = await self._request_safety(reader, fact, at, release=True)
        for action, errors in (("review", ordinary), ("reject", release)):
            if errors:
                denials[action] = errors
            else:
                actions.append(action)
        start = ordinary + self._authenticate(
            fact.requisites, fact.row["recipient_id"]
        )
        account = self.config.manual_bank_account_id
        if (
            not isinstance(account, str)
            or not account.strip()
            or len(account) > 256
        ):
            start.append("payout_bank_account_configuration_required")
        source = self.config.manual_bank_source_id
        if (
            not isinstance(source, str)
            or not source.strip()
            or len(source) > 256
        ):
            start.append("payout_bank_source_configuration_required")
        if state == "approved" and not start:
            actions.append("start")
        else:
            denials["start"] = blockers(
                start or ["payout_review_approval_required"]
            )
        return actions, denials

    async def detail(self, principal, request_id):
        async with self.repository.snapshot() as reader:
            actor = await self._actor(reader, principal)
            fact = await reader.request(
                request_id,
                None
                if actor.admin and actor.status == "active"
                else actor.actor_id,
            )
            if fact is None:
                raise PayoutReadNotFound("payout_read_not_found")
            return payout_to_wire(
                canonical(await self._detail(reader, actor, fact, self._at()))
            )

    async def own_page(self, principal, *, page=DEFAULT_PAGE):
        async with self.repository.snapshot() as reader:
            actor = await self._actor(reader, principal)
            at = self._at()
            rows = await reader.requests(
                actor.actor_id,
                page,
                cursor_decode(page.cursor, principal, "own"),
                queue=False,
            )
            result = self._page(
                rows,
                page,
                principal,
                "own",
                position="requested_at",
                identity="request_id",
                render=lambda row: self._request_view(row, at),
            )
            return payout_to_wire(canonical(result | {"as_of": at}))

    async def queue_page(self, principal, *, page=DEFAULT_PAGE):
        async with self.repository.snapshot() as reader:
            actor = await self._actor(reader, principal, admin=True)
            at = self._at()
            rows = await reader.requests(
                None,
                page,
                cursor_decode(page.cursor, principal, "queue"),
                queue=True,
            )
            result = self._page(
                rows,
                page,
                principal,
                "queue",
                position="requested_at",
                identity="request_id",
                render=lambda row: self._request_view(row, at),
            )
            result["entries"] = [
                await self._detail(reader, actor, row, at)
                for row in rows[: page.limit]
            ]
            return payout_to_wire(canonical(result | {"as_of": at}))

    async def masked_page(self, principal, *, page=DEFAULT_PAGE):
        async with self.repository.snapshot() as reader:
            actor = await self._actor(reader, principal)
            at = self._at()
            requirements = await reader.requirements(at)
            rows = await reader.requisites(
                actor.actor_id,
                page,
                cursor_decode(page.cursor, principal, "masked"),
            )
            return canonical(
                self._page(
                    rows,
                    page,
                    principal,
                    "masked",
                    render=lambda row: self._masked(
                        row, requirements.current, actor.actor_id
                    ),
                )
                | {"as_of": at}
            )

    async def requirements_page(self, principal, *, page=DEFAULT_PAGE):
        async with self.repository.snapshot() as reader:
            await self._actor(reader, principal, admin=True)
            at = self._at()
            rows = await reader.requirements_page(
                page, cursor_decode(page.cursor, principal, "requirements")
            )
            return canonical(
                self._page(
                    rows,
                    page,
                    principal,
                    "requirements",
                    identity="requirements_id",
                    render=lambda row: requirement(row, admin=True),
                )
                | {"as_of": at}
            )

    async def history_page(
        self, principal, request_id, kind, *, page=DEFAULT_PAGE
    ):
        if kind not in ("events", "intents", "outcomes", "settlements"):
            raise ValueError("payout_cursor_invalid")
        async with self.repository.snapshot() as reader:
            await self._actor(reader, principal, admin=True)
            fact = await reader.request(request_id, None)
            if fact is None:
                raise PayoutReadNotFound("payout_read_not_found")
            at = self._at()
            route = "history:" + kind
            rows = await reader.history(
                request_id,
                kind,
                page,
                cursor_decode(page.cursor, principal, route, request_id),
            )
            position, identity = {
                "events": ("version", "event_id"),
                "intents": ("prepared_at", "execution_id"),
                "outcomes": ("recorded_at", "outcome_id"),
                "settlements": ("settled_at", "execution_id"),
            }[kind]
            keys = {
                "events": {
                    "event_id",
                    "request_id",
                    "version",
                    "action",
                    "state",
                    "actor_id",
                    "reason",
                    "recorded_at",
                },
                "intents": {
                    "execution_id",
                    "request_id",
                    "actor_id",
                    "fence",
                    "amount_minor",
                    "currency",
                    "bank_account",
                    "prepared_at",
                    "version",
                    "version_provenance",
                },
                "outcomes": {
                    "outcome_id",
                    "request_id",
                    "execution_id",
                    "actor_id",
                    "status",
                    "amount_minor",
                    "currency",
                    "settled_at",
                    "bank_account",
                    "bank_reference",
                    "evidence_reference",
                    "evidence_hash",
                    "recorded_at",
                    "applied",
                    "review_reason",
                },
                "settlements": {
                    "execution_id",
                    "request_id",
                    "outcome_id",
                    "amount_minor",
                    "currency",
                    "bank_account",
                    "bank_reference",
                    "settled_at",
                },
            }[kind]

            def render(row):
                value = {k: v for k, v in row.items() if k in keys}
                if kind == "events":
                    details = row.get("details")
                    if isinstance(details, dict):
                        projection = details.get("projection")
                        if (
                            isinstance(projection, dict)
                            and set(projection)
                            == {
                                "request_id",
                                "version",
                                "state",
                                "execution_id",
                                "block_reason",
                            }
                            and type(projection["version"]) is int
                            and projection["version"] == row["version"]
                            and projection["state"] == row["state"]
                            and projection["block_reason"]
                            in PUBLIC_PAYOUT_BLOCK_CODES
                        ):
                            value["resulting_state"] = {
                                k: projection[k]
                                for k in (
                                    "request_id",
                                    "version",
                                    "state",
                                    "execution_id",
                                    "block_reason",
                                )
                            }
                        evidence = details.get("evidence_reference")
                        if isinstance(evidence, str):
                            value["evidence_reference"] = evidence
                if "review_reason" in value:
                    value["review_reason"] = (
                        blockers([value["review_reason"]])[0]
                        if value["review_reason"]
                        else ""
                    )
                return value

            return payout_to_wire(
                canonical(
                    self._page(
                        rows,
                        page,
                        principal,
                        route,
                        scope=request_id,
                        position=position,
                        identity=identity,
                        render=render,
                    )
                    | {"as_of": at, "kind": kind}
                )
            )
