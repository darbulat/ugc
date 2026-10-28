"""Bounded correction UI hints; commands recheck every live source."""

from dataclasses import asdict
from uuid import UUID

from ugc_bot.application.collaboration_ports import canonical
from ugc_bot.domain.corrections import require_minor, require_uuid, uuid_tuple
from ugc_bot.domain.financial import utc


def page_position(limit, cursor):
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("correction_read_request_invalid")
    try:
        identity = UUID(cursor) if cursor is not None else None
        if identity is not None:
            require_uuid(identity)
    except (ValueError, TypeError, AttributeError):
        raise ValueError("correction_read_request_invalid") from None
    return identity


def request_total(request):
    bundle = request.get("bundle") if request else None
    if bundle is None:
        return None
    if type(bundle) is not list or not bundle:
        raise ValueError("correction_source_unavailable")
    total = 0
    for component in bundle:
        require_minor(component["gross_minor"], positive=True)
        total += component["gross_minor"]
    require_minor(total, positive=True)
    return total


class CorrectionViewService:
    def __init__(self, repository, commands, clock, config):
        self.repository = repository
        self.commands = commands
        self.clock = clock
        self.config = config

    @property
    def paused(self):
        return not self.config.core_enabled

    async def _actor(self, actor_id, principal, session, *, admin=False):
        require_uuid(actor_id)
        scope = await self.repository.discover_case_scope(
            actor_id, None, session=session
        )
        return await self.commands.authorize_read(
            scope,
            action="admin" if admin else "context",
            session=session,
            principal=principal,
        )

    def _at(self):
        return utc(self.clock.now())

    async def context(self, actor_id, *, principal, session):
        actor = await self._actor(actor_id, principal, session)
        admin = actor.admin and actor.status == "active"
        return canonical(
            dict(
                actor_id=actor.user_id,
                admin=admin,
                as_of=self._at(),
                writes_paused=self.paused,
                capabilities=dict(
                    read_own_cases=True,
                    read_admin_queue=admin,
                    request=False,
                    review=admin and not self.paused,
                    record_observation=admin,
                    match=admin and not self.paused,
                    apply=admin and not self.paused,
                ),
            )
        )

    def _page(self, entries, rows, limit, identity):
        return canonical(
            dict(
                entries=entries,
                has_more=len(rows) > limit,
                next_cursor=str(rows[limit - 1][identity])
                if len(rows) > limit
                else None,
                as_of=self._at(),
            )
        )

    def _summary(self, row, state, valid, *, admin):
        request = row.get("request")
        return canonical(
            dict(
                case_id=row["case_id"],
                order_id=request["order_id"] if request else row["order_id"],
                paid_item_ids=request["paid_item_ids"] if request else [],
                total_minor=request_total(request),
                currency="RUB",
                recorded_at=row["recorded_at"],
                current=asdict(state) if state and valid else None,
                state_unavailable=not valid,
                allowed_actions=["record_observation"] if admin else [],
            )
        )

    async def cases(
        self,
        actor_id,
        *,
        principal,
        session,
        admin=False,
        limit=20,
        cursor=None,
    ):
        after = page_position(limit, cursor)
        actor = await self._actor(actor_id, principal, session, admin=admin)
        rows = await self.repository.cases_page(
            actor.user_id,
            admin=admin,
            limit=limit,
            after=after,
            session=session,
        )
        entries = []
        for row in rows[:limit]:
            state, valid = await self.repository.state_authority(
                row["case_id"], session=session
            )
            entries.append(self._summary(row, state, valid, admin=admin))
        return self._page(entries, rows, limit, "case_id")

    async def orders(
        self, actor_id, *, principal, session, limit=20, cursor=None
    ):
        after = page_position(limit, cursor)
        await self._actor(actor_id, principal, session)
        rows = await self.repository.orders_page(
            actor_id, limit=limit, after=after, session=session
        )
        return self._page(rows[:limit], rows, limit, "order_id")

    async def preview(
        self,
        actor_id,
        order_id,
        paid_item_ids,
        *,
        principal,
        session,
        existing_case_id=None,
    ):
        require_uuid(actor_id)
        require_uuid(order_id)
        if existing_case_id is not None:
            require_uuid(existing_case_id)
        selected = uuid_tuple(paid_item_ids)
        if not 1 <= len(selected) <= 30:
            raise ValueError("correction_selection_required")
        scope = await self.repository.discover_preview(
            actor_id,
            order_id,
            selected,
            existing_case_id=existing_case_id,
            session=session,
        )
        actor = await self.commands.authorize_read(
            scope, action="preview", session=session, principal=principal
        )
        facts = await self.repository.facts(scope, session=session)
        requests = facts.rows("requests")
        refusal = self.commands._refusal(scope, self._at())
        blockers = [refusal] if refusal else []
        if self.paused:
            blockers.append("financial_corrections_disabled")
        return canonical(
            dict(
                order_id=order_id,
                paid_item_ids=selected,
                existing_case_id=existing_case_id,
                source_hash=scope.source_hash,
                total_minor=scope.bundle.total_minor if scope.bundle else None,
                currency="RUB",
                components=[
                    dict(
                        paid_item_id=c.paid_item_id,
                        gross_minor=c.gross_minor,
                        selection_due_at=c.selection_due_at,
                    )
                    for c in scope.bundle.components
                ]
                if scope.bundle
                else [],
                blockers=blockers,
                can_request=False,
                can_approve=not self.paused
                and actor.admin
                and not refusal
                and len(requests) == 1
                and requests[0]["source_hash"] == scope.source_hash,
                as_of=self._at(),
            )
        )

    async def detail(self, actor_id, case_id, *, principal, session):
        require_uuid(case_id)
        scope = await self.repository.discover_case_scope(
            actor_id, case_id, session=session
        )
        actor = await self.commands.authorize_read(
            scope, action="case", session=session, principal=principal
        )
        facts = await self.repository.facts(scope, session=session)
        cases, requests = facts.rows("cases"), facts.rows("requests")
        if not cases:
            raise LookupError("correction_not_found")
        request = requests[0] if requests else None
        state, valid = await self.repository.state_authority(
            case_id, session=session
        )
        result = self._summary(
            cases[0] | dict(request=request), state, valid, admin=actor.admin
        )
        self._actions(result, scope, actor, state, valid, request)
        events = sorted(facts.rows("events"), key=lambda row: row["version"])
        own = next(
            (
                event
                for event in events
                if request and event["command_id"] == request["command_id"]
            ),
            None,
        )
        result["request"] = (
            {k: request[k] for k in ("request_id", "recorded_at")}
            | {"reason": own["reason"] if own else None}
            if request
            else None
        )
        result["events"] = [
            self._event(row, admin=actor.admin) for row in events
        ]
        result["as_of"] = canonical(self._at())
        result["available_items"] = (
            await self.repository.order_positions(
                scope.order_id, session=session
            )
            if not request
            and scope.order_id is not None
            and scope.client_id == actor.user_id
            else []
        )
        if actor.admin:
            for kind in ("intents", "observations", "matches"):
                result[kind] = facts.rows(kind)
            applicable = self._applicable_matches(facts, scope, state, request)
            result["applicable_matches"] = applicable
            if (
                applicable
                and valid
                and not self.paused
                and state is not None
                and state.review_status == "approved"
                and state.match_status == "matched"
                and state.application_status != "applied"
            ):
                result["allowed_actions"].append("apply")
        return canonical(result)

    def _applicable_matches(self, facts, scope, state, request):
        """Expose matches backed by their retained reviewed command receipt."""
        if (
            state is None
            or request is None
            or state.source_hash != scope.source_hash
        ):
            return []
        result = []
        for match in facts.rows("matches"):
            if match.get("source_hash") != scope.source_hash:
                continue
            try:
                intent = facts.one("intents", "intent_id", match["intent_id"])
                self.commands._match_links(facts, intent, request)
                receipt = facts.one(
                    "commands", "command_id", match["command_id"]
                )
                if (
                    receipt.get("action") == "MatchSelectionRefund"
                    and receipt.get("result", {}).get("match_id")
                    == match["match_id"]
                ):
                    result.append(match)
            except (ValueError, KeyError, LookupError):
                continue
        return result

    def _actions(self, result, scope, actor, state, valid, request):
        actions = result["allowed_actions"]
        if self.paused or not valid or state is None:
            return
        if (
            actor.admin
            and request
            and request["source_hash"] == scope.source_hash
            and state.source_hash == scope.source_hash
        ):
            actions.append("review")
            if state.review_status == "approved" and state.observation_ids:
                actions.append("match")

    @staticmethod
    def _event(row, *, admin):
        result = {k: row[k] for k in ("version", "recorded_at")}
        result.update(
            {
                k: row["result_state"][k]
                for k in ("review_status", "match_status", "application_status")
            }
        )
        if admin:
            result.update(
                {
                    k: row[k]
                    for k in ("reason", "evidence_reference", "evidence_hash")
                }
            )
        return result
