"""Partner reads preserve snapshot economics and never create a wallet."""

import re
from dataclasses import replace
from typing import Any
from uuid import UUID

from ugc_bot.application.financial_ports import Clock, ObligationBasis
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.application.partner_view_ports import (
    KINDS,
    PAGE_SIZE,
    PartnerFinancialFacts,
    PartnerViewRepository,
)
from ugc_bot.application.services.financial_reconciliation_service import (
    BUCKETS,
    replay_journal,
    validate_issuance,
)
from ugc_bot.domain.financial import utc


def _minor(balances):
    return {key: str(value) for key, value in balances.items()}


def _financial(facts: PartnerFinancialFacts | None, actor_id, page):
    empty: dict[str, Any] = {
        "state": "unavailable",
        "currency": "RUB",
        "balances": None,
        "projection": None,
        "groups": [],
        "history": {"entries": [], "page": page, "has_more": False},
    }
    if facts is None:
        return empty
    if (
        not facts.obligations
        and not facts.movements
        and facts.projection is None
    ):
        return {**empty, "state": "uninitialized"}
    entries = tuple(row.movement for row in facts.movements)
    bases = tuple(
        ObligationBasis(o.obligation_id, actor_id, "RUB", o.amount_minor)
        for o in facts.obligations
    )
    replay = replay_journal(entries, currency="RUB")
    replay = replace(
        replay,
        errors=replay.errors
        + validate_issuance(
            entries, bases, recipient_id=actor_id, currency="RUB"
        ),
    )
    ready = replay.balanced and facts.projection == replay.balances
    by_id = {row.obligation_id: row for row in facts.obligations}
    groups = []
    for kind in KINDS:
        own = [o for o in facts.obligations if o.kind == kind]
        balances = {
            key: sum(
                replay.by_obligation.get(o.obligation_id, {}).get(key, 0)
                for o in own
            )
            for key in BUCKETS
        }
        groups.append(
            {
                "kind": kind,
                "balances": _minor(balances),
                "obligations_count": len(own),
            }
        )
    history = []
    rows = tuple(reversed(facts.movements))
    for row in rows[page * PAGE_SIZE : (page + 1) * PAGE_SIZE]:
        entry = row.movement
        obligation = by_id.get(entry.obligation_id)
        if obligation is None:
            continue
        history.append(
            {
                "movement_id": str(row.movement_id),
                "obligation_id": str(obligation.obligation_id),
                "order_id": str(obligation.order_id),
                "paid_item_id": str(obligation.paid_item_id),
                "assignment_id": str(obligation.assignment_id)
                if obligation.assignment_id
                else None,
                "kind": obligation.kind,
                "base_minor": str(obligation.base_minor),
                "rate_bps": obligation.rate_bps,
                "rate_source": obligation.rate_source,
                "policy_version": obligation.policy_version,
                "snapshot_at": obligation.snapshot_at,
                "registered_at": obligation.registered_at,
                "snapshot_verified_count": obligation.verified_count,
                "amount_minor": str(entry.amount_minor),
                "movement_type": entry.movement_type,
                "bucket_from": entry.bucket_from,
                "bucket_to": entry.bucket_to,
                "effective_at": entry.effective_at,
                "recorded_at": entry.recorded_at,
            }
        )
    return {
        "state": "ready" if ready else "mismatch",
        "currency": "RUB",
        "balances": _minor(replay.balances),
        "projection": _minor(facts.projection)
        if facts.projection is not None
        else None,
        "groups": groups,
        "history": {
            "entries": history,
            "page": page,
            "has_more": len(rows) > (page + 1) * PAGE_SIZE,
        },
    }


class PartnerViewService:
    def __init__(
        self,
        repository: PartnerViewRepository,
        clock: Clock,
        referral_usernames: dict[str, str],
    ):
        self.repository, self.clock = repository, clock
        self.referral_usernames = referral_usernames

    def _link(self, platform, code):
        username = self.referral_usernames.get(platform, "").strip().lstrip("@")
        if not re.fullmatch(
            r"[A-Za-z0-9_.-]{1,64}", username
        ) or not re.fullmatch(r"[a-z0-9]{4,20}", code or ""):
            return None
        host = "t.me" if platform == "telegram" else "max.ru"
        return f"https://{host}/{username}?start=ref_{code}"

    async def view(
        self,
        actor_id: UUID,
        *,
        platform: str,
        network_page: int = 0,
        history_page: int = 0,
        assignment_page: int = 0,
        writes_paused: bool,
        session: object,
        principal: AuthenticatedMessengerPrincipal | None = None,
    ):
        if principal is not None and (
            not isinstance(principal, AuthenticatedMessengerPrincipal)
            or principal.user_id != actor_id
        ):
            raise ValueError("financial_principal_changed")
        if platform not in ("telegram", "max") or any(
            type(page) is not int or not 0 <= page <= 100000
            for page in (network_page, history_page, assignment_page)
        ):
            raise ValueError("invalid_partner_page")
        at = utc(self.clock.now())
        facts = await self.repository.read(
            actor_id,
            at,
            network_page=network_page,
            assignment_page=assignment_page,
            session=session,
            principal=principal,
        )
        if facts is None:
            raise LookupError("partner_not_found")
        if facts.actor_id != actor_id:
            raise PermissionError("partner_scope_mismatch")
        if facts.account_status in ("blocked", "deleted"):
            raise PermissionError("partner_account_unavailable")
        count = facts.verified_creators
        threshold, rate = next(
            (minimum, rate)
            for minimum, rate in (
                (400, 2000),
                (200, 1500),
                (100, 1200),
                (0, 1000),
            )
            if count >= minimum
        )
        next_threshold = next((n for n in (100, 200, 400) if n > count), None)
        return {
            "actor_id": str(actor_id),
            "as_of": at,
            "account_status": facts.account_status,
            "writes_paused": writes_paused,
            "referral": {"link": self._link(platform, facts.referral_code)},
            "grade": {
                "verified_creators": count,
                "source": "canonical_current_instagram",
                "threshold": threshold,
                "tier_rate_bps": rate,
                "next_threshold": next_threshold,
                "remaining": next_threshold - count if next_threshold else None,
            },
            "standards": {
                "client_first_year_bps": 1000,
                "after_year_bps": 300,
                "creator_tiers": [
                    {"threshold": n, "rate_bps": rate}
                    for n, rate in (
                        (0, 1000),
                        (100, 1200),
                        (200, 1500),
                        (400, 2000),
                    )
                ],
            },
            "network": {
                "members": facts.network_members,
                "total": facts.network_total,
                "page": network_page,
                "has_more": facts.network_total
                > (network_page + 1) * PAGE_SIZE,
            },
            "financial": _financial(facts.financial, actor_id, history_page),
            "overrides": {
                "state": "available"
                if facts.overrides is not None
                else "unavailable",
                "entries": facts.overrides or (),
            },
            "assignments": {
                "state": "available"
                if facts.assignments is not None
                else "unavailable",
                "entries": facts.assignments or (),
                "page": assignment_page,
                "total": facts.assignment_total,
                "has_more": facts.assignment_total is not None
                and facts.assignment_total > (assignment_page + 1) * PAGE_SIZE,
            },
        }
