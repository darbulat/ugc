"""The inventory is read-only on the actual migrated PostgreSQL schema."""

import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import sqlalchemy as sa

from tests.postgres_financial.test_creator_social import (
    profile_values,
    seed_user,
)
from ugc_bot.infrastructure.db.instagram_discovery_models import DISCOVERY as D
from ugc_bot.infrastructure.db.instagram_discovery_models import (
    DISCOVERY_CONTROL as C,
)
from ugc_bot.infrastructure.db.instagram_maintenance_models import HEALTH as H
from ugc_bot.infrastructure.db.models import AuditLogModel as A
from ugc_bot.infrastructure.db.models import BloggerProfileModel as P
from ugc_bot.infrastructure.db.models import InstagramStatsModel as S
from ugc_bot.infrastructure.db.models import UserModel as U
from ugc_bot.instagram_data_quality_report import collect_report

NOW = datetime(2026, 11, 20, 8, tzinfo=timezone.utc)
CONTEXT = "quality-test-context"


def test_inventory_counts_actual_evidence_not_attempts_and_never_writes(
    financial_pg_engine,
):
    engine = financial_pg_engine
    empty = collect_report(engine, CONTEXT, at=NOW)
    assert empty["totals"] == {} and empty["discovery_control"] is None
    owners = []
    with engine.begin() as db:
        for i in range(4):
            owner = seed_user(db)
            owners.append(owner)
            handle = "c" + owner.hex[:20]
            values = profile_values(
                owner,
                stable_id=str(i + 1) if i != 2 else None,
                confirmed=i != 2,
            )
            values.update(
                instagram_username=handle,
                city="PRIVATE_CITY_DO_NOT_OUTPUT" if i == 0 else "",
                audience_geo="",
                instagram_followers_count=[0, 20, None, 30][i],
                instagram_stats_fetched_at=NOW
                - timedelta(days=[3, 20, 0, 2][i])
                if i != 2
                else None,
            )
            db.execute(P.__table__.insert().values(**values))
            if i == 2:
                db.execute(
                    sa.update(U)
                    .where(U.user_id == owner)
                    .values(status="bot_blocked")
                )
                continue
            since = NOW - timedelta(days=1 if i == 3 else 30)
            observed = NOW - timedelta(days=20 if i == 1 else 2)
            db.execute(
                H.insert().values(
                    user_id=owner,
                    meta_id=str(i + 1),
                    id_kind="instagram_scoped_id",
                    identity_context=CONTEXT,
                    handle=handle,
                    status="healthy",
                    failure_count=0,
                    identity_since=since,
                    metrics_observed_at=observed,
                    last_success_at=NOW - timedelta(hours=1),
                    checked_at=NOW,
                    episode=uuid4(),
                )
            )
            if i in (1, 3):
                db.execute(
                    S.__table__.insert().values(
                        user_id=owner,
                        raw_response={"private": "RAW_RESPONSE_DO_NOT_READ"},
                        fetched_at=NOW,
                        instagram_username=handle
                        if i == 1
                        else "previous_handle",
                        followers_count=999,
                        media_count=77,
                    )
                )
            details = {
                "name": {
                    "value": "PRIVATE_NAME_DO_NOT_OUTPUT",
                    "observed_at": NOW.isoformat(),
                }
            }
            if i == 0:
                details.update(
                    {
                        "follows_count": {
                            "value": 0,
                            "observed_at": NOW.isoformat(),
                        },
                        "has_profile_pic": {
                            "value": False,
                            "observed_at": NOW.isoformat(),
                        },
                        "biography": {
                            "value": "PRIVATE_BIO_DO_NOT_OUTPUT",
                            "observed_at": NOW.isoformat(),
                        },
                    }
                )
            elif i == 1:
                details["name"]["observed_at"] = "invalid"
            db.execute(
                D.insert().values(
                    user_id=owner,
                    observed_meta_id=str(i + 1),
                    identity_context=CONTEXT if i != 3 else "old-context",
                    username=handle,
                    followers_count=110 if i == 0 else 200 if i == 3 else None,
                    followers_observed_at=NOW if i in (0, 3) else None,
                    media_count=12 if i == 0 else None,
                    media_observed_at=NOW if i == 0 else None,
                    observed_at=NOW,
                    details=details,
                    attempt_meta_id=str(i + 1),
                    attempt_profile_url=values["instagram_url"],
                    attempt_id=uuid4(),
                    attempted_at=NOW,
                    next_attempt_at=NOW + timedelta(days=14)
                    if i != 3
                    else NOW - timedelta(minutes=1),
                    last_outcome="invalid_request" if i == 3 else "success",
                )
            )
        db.execute(
            C.insert().values(
                singleton=1,
                next_run_at=NOW + timedelta(days=1),
                requests_used=3,
                last_outcome="invalid_request",
            )
        )
        db.execute(
            A.__table__.insert().values(
                id=uuid4(),
                entity_type="bot_unavailable",
                entity_id=owners[3],
                action="create",
                new_values={
                    "platform": "telegram",
                    "telegram_id": str(owners[3]),
                },
                changed_at=NOW,
            )
        )
        before = (
            db.execute(sa.select(P.__table__).order_by(P.user_id))
            .mappings()
            .all()
        )

    statements = []
    read_only = []

    def watch(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)
        if statement.lstrip().startswith("SELECT"):
            cursor.execute("SHOW transaction_read_only")
            read_only.append(cursor.fetchone()[0])

    sa.event.listen(engine, "before_cursor_execute", watch)
    try:
        report = collect_report(engine, CONTEXT, at=NOW)
    finally:
        sa.event.remove(engine, "before_cursor_execute", watch)
    assert read_only and set(read_only) == {"on"}
    assert all("raw_response" not in x.lower() for x in statements)
    assert report["totals"] == {
        "profiles": 4,
        "confirmed": 3,
        "without_meta_id": 1,
        "bot_unavailable": 2,
        "legacy_attempted_within_window": 2,
    }
    fields = report["fields"]
    assert fields["primary_followers"] == {
        "fresh": 1,
        "stale": 1,
        "missing": 1,
        "before_current_identity": 1,
    }
    assert fields["legacy_followers"] == {
        "missing": 2,
        "stale": 1,
        "identity_mismatch": 1,
    }
    assert fields["discovery_followers"] == {
        "fresh": 1,
        "missing": 2,
        "identity_mismatch": 1,
    }
    assert fields["discovery_media"] == {"fresh": 1, "missing": 3}
    assert fields["discovery_has_profile_pic"] == {"fresh": 1, "missing": 3}
    assert fields["discovery_follows_count"] == {"fresh": 1, "missing": 3}
    assert fields["discovery_name"] == {
        "fresh": 1,
        "invalid_timestamp": 1,
        "missing": 1,
        "identity_mismatch": 1,
    }
    assert report["discovery_queue"]["eligible"] == 3
    assert report["discovery_queue"]["due"] == 1
    assert report["manual_field_gaps"] == {
        "city_missing": 3,
        "audience_geo_missing": 4,
        "topics_missing": 4,
    }
    assert report["discovery_control"]["requests_used"] == 3
    assert all(sum(states.values()) == 4 for states in fields.values())
    encoded = json.dumps(report, default=str)
    assert not any(
        secret in encoded
        for secret in ["PRIVATE_", "RAW_RESPONSE_DO_NOT_READ", str(owners[0])]
    )
    with engine.connect() as db:
        assert (
            db.execute(sa.select(P.__table__).order_by(P.user_id))
            .mappings()
            .all()
            == before
        )
