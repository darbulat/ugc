"""Aggregate existing data in a read-only transaction; no social API clients."""

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa

from ugc_bot.domain.instagram_discovery import utc
from ugc_bot.infrastructure.db.instagram_discovery_models import DISCOVERY as D
from ugc_bot.infrastructure.db.instagram_discovery_models import (
    DISCOVERY_CONTROL as C,
)
from ugc_bot.infrastructure.db.instagram_maintenance_models import HEALTH as H
from ugc_bot.infrastructure.db.models import BloggerProfileModel as P
from ugc_bot.infrastructure.db.models import InstagramStatsModel as S
from ugc_bot.infrastructure.db.models import UserModel as U
from ugc_bot.infrastructure.db.repositories.bot_availability import (
    creator_directory_status,
)
from ugc_bot.infrastructure.db.repositories.instagram_discovery import (
    DiscoveryRepository,
)

DETAIL_FIELDS = (
    "follows_count",
    "name",
    "biography",
    "website",
    "profile_picture_url",
    "has_profile_pic",
)


def field_state(
    known: bool,
    observed_at: datetime | str | None,
    *,
    at: datetime,
    days: int,
    bound: bool = True,
    since: datetime | None = None,
) -> str:
    """Missing, undated and stale are different; an attempt is not evidence."""
    if not known:
        return "missing"
    if not bound:
        return "identity_mismatch"
    try:
        observed = (
            datetime.fromisoformat(observed_at)
            if isinstance(observed_at, str)
            else observed_at
        )
        observed = utc(observed) if observed is not None else None
    except ValueError:
        return "invalid_timestamp"
    if since is not None and (observed is None or observed < utc(since)):
        return "before_current_identity"
    if observed is None:
        return "undated"
    if observed > at:
        return "future_timestamp"
    return "fresh" if observed >= at - timedelta(days=days) else "stale"


def _query(context, at):
    query = (
        sa.select(
            P.confirmed,
            P.instagram_user_id.label("meta_id"),
            P.instagram_username.label("handle"),
            P.instagram_url.label("profile_url"),
            P.instagram_followers_count.label("primary_followers"),
            P.instagram_stats_fetched_at.label("primary_at"),
            P.city.label("city"),
            (sa.cast(P.topics, sa.String).not_in(("{}", "[]", "null"))).label(
                "topics_present"
            ),
            P.audience_geo.label("audience_geo"),
            U.status.label("status"),
            creator_directory_status().label("directory_status"),
            H.c.status.label("health_status"),
            H.c.identity_context.label("health_context"),
            H.c.identity_since,
            H.c.metrics_observed_at,
            S.followers_count.label("legacy_followers"),
            S.media_count.label("legacy_media"),
            S.instagram_username.label("legacy_handle"),
            S.fetched_at.label("legacy_attempt_at"),
            D.c.observed_meta_id,
            D.c.identity_context.label("discovery_identity_context"),
            D.c.username.label("discovery_handle"),
            D.c.followers_count.label("discovery_followers"),
            D.c.followers_observed_at,
            D.c.media_count.label("discovery_media"),
            D.c.media_observed_at,
            D.c.attempt_meta_id,
            D.c.attempt_profile_url,
            D.c.next_attempt_at,
            D.c.last_outcome,
            DiscoveryRepository(None, context)
            ._eligible(at)
            .label("discovery_eligible"),
        )
        .select_from(P)
        .join(U, U.user_id == P.user_id)
        .outerjoin(
            H,
            sa.and_(
                H.c.user_id == P.user_id, H.c.meta_id == P.instagram_user_id
            ),
        )
        .outerjoin(S, S.user_id == P.user_id)
        .outerjoin(D, D.c.user_id == P.user_id)
    )
    for name in DETAIL_FIELDS:
        query = query.add_columns(
            D.c.details[name]["value"]
            .as_string()
            .is_not(None)
            .label(name + "_known"),
            D.c.details[name]["observed_at"].as_string().label(name + "_at"),
        )
    return query


def _record_fields(
    row: sa.RowMapping,
    fields: dict[str, Counter[str]],
    *,
    context: str,
    at: datetime,
    days: int,
) -> None:
    since = row["identity_since"]
    bound = (
        row["observed_meta_id"] == row["meta_id"]
        and row["discovery_identity_context"] == context
        and (row["discovery_handle"] or "").lower()
        == (row["handle"] or "").lower()
    )
    legacy_bound = since is None or (
        (row["legacy_handle"] or "").lower() == (row["handle"] or "").lower()
    )
    metrics = (
        ("primary_followers", "primary_at", True),
        ("legacy_followers", "metrics_observed_at", legacy_bound),
        ("legacy_media", "metrics_observed_at", legacy_bound),
        ("discovery_followers", "followers_observed_at", bound),
        ("discovery_media", "media_observed_at", bound),
    )
    for name, date, binding in metrics:
        value = row[name]
        state = field_state(
            type(value) is int and value >= 0,
            row[date],
            at=at,
            days=days,
            bound=binding,
            since=since,
        )
        fields[name][state] += 1
    for name in DETAIL_FIELDS:
        state = field_state(
            row[name + "_known"],
            row[name + "_at"],
            at=at,
            days=days,
            bound=bound,
            since=since,
        )
        fields["discovery_" + name][state] += 1


def collect_report(
    engine: sa.Engine,
    context: str,
    *,
    at: datetime,
    days: int = 14,
) -> dict:
    """All SQL runs under PostgreSQL READ ONLY, bounded by local timeouts."""
    if engine.dialect.name != "postgresql" or not context.strip():
        raise ValueError(
            "PostgreSQL and an explicit identity context are required"
        )
    if at.utcoffset() is None or not 1 <= days <= 365:
        raise ValueError(
            "An aware time and freshness days from 1 to 365 are required"
        )
    at = utc(at)
    totals: Counter[str] = Counter()
    statuses: Counter[str] = Counter()
    health: Counter[str] = Counter()
    queue: Counter[str] = Counter()
    manual: Counter[str] = Counter()
    fields: dict[str, Counter[str]] = defaultdict(Counter)
    with engine.connect().execution_options(
        isolation_level="REPEATABLE READ"
    ) as db:
        db.execute(sa.text("SET TRANSACTION READ ONLY"))
        db.execute(sa.text("SET LOCAL lock_timeout = '1s'"))
        db.execute(sa.text("SET LOCAL statement_timeout = '15s'"))
        for row in db.execute(_query(context, at)).mappings():
            totals["profiles"] += 1
            totals["confirmed"] += bool(row["confirmed"])
            totals["without_meta_id"] += not bool(row["meta_id"])
            totals["bot_unavailable"] += (
                row["directory_status"] == "bot_blocked"
            )
            statuses[str(row["status"])] += 1
            health[
                row["health_status"]
                if row["health_context"] == context
                else "not_checked_in_current_context"
            ] += 1
            for key in ("city", "audience_geo"):
                manual[key + "_missing"] += not bool((row[key] or "").strip())
            manual["topics_missing"] += not bool(row["topics_present"])
            _record_fields(row, fields, context=context, at=at, days=days)
            if row["discovery_eligible"]:
                queue["eligible"] += 1
                due = (
                    row["next_attempt_at"] is None
                    or row["next_attempt_at"] <= at
                    or row["attempt_meta_id"] != row["meta_id"]
                    or row["attempt_profile_url"] != row["profile_url"]
                )
                queue["due"] += due
            if row["legacy_attempt_at"] and utc(
                row["legacy_attempt_at"]
            ) >= at - timedelta(days=days):
                totals["legacy_attempted_within_window"] += 1
            if row["last_outcome"]:
                queue["outcome_" + row["last_outcome"]] += 1
        control = (
            db.execute(
                sa.select(C.c.next_run_at, C.c.requests_used, C.c.last_outcome)
            )
            .mappings()
            .one_or_none()
        )
        db.rollback()
    return {
        "as_of": at.isoformat(),
        "freshness_days": days,
        "scope": "all blogger profiles; source fields are counted separately",
        "totals": dict(totals),
        "account_statuses": dict(statuses),
        "profile_health": dict(health),
        "fields": dict(fields),
        "manual_field_gaps": dict(manual),
        "discovery_queue": dict(queue),
        "discovery_control": dict(control) if control else None,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fresh-days", type=int, default=14)
    args = parser.parse_args(argv)
    engine = None
    try:
        engine = sa.create_engine(
            os.environ["DATABASE_URL"],
            hide_parameters=True,
            connect_args={"connect_timeout": 10},
        )
        report = collect_report(
            engine,
            os.environ["INSTAGRAM_IDENTITY_CONTEXT"],
            at=datetime.now(timezone.utc),
            days=args.fresh_days,
        )
        print(json.dumps(report, default=str, sort_keys=True, indent=2))
        return 0
    except Exception as exc:
        print(
            f"Data quality report failed ({type(exc).__name__})",
            file=sys.stderr,
        )
        return 1
    finally:
        if engine is not None:
            engine.dispose()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
