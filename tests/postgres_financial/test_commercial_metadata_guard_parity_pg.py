"""Commercial fact guards behave equally after migrations and metadata DDL."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.models import UserModel
from ugc_bot.infrastructure.db.partner_admin_models import BINDING_CORRECTIONS
from ugc_bot.infrastructure.db.subscription_models import SUBSCRIPTIONS


@pytest.fixture(params=("migrations", "metadata"))
def commercial_connection(request, financial_pg_engine):
    with financial_pg_engine.connect() as connection:
        transaction = connection.begin()
        try:
            if request.param == "metadata":
                schema = "commercial_metadata_" + uuid4().hex
                connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                connection.execute(
                    text(f'SET LOCAL search_path TO "{schema}", public')
                )
                Base.metadata.create_all(connection)
                Base.metadata.create_all(connection)
            yield connection
        finally:
            transaction.rollback()


def _user(connection, *, admin=False):
    user_id = uuid4()
    connection.execute(
        UserModel.__table__.insert().values(
            user_id=user_id,
            messenger_type="telegram",
            username="synthetic-metadata-guard",
            status="active",
            admin=admin,
        )
    )
    return user_id


def _subscription(connection, actor, member, sequence, action="publish"):
    event_id = uuid4()
    connection.execute(
        SUBSCRIPTIONS.insert().values(
            event_id=event_id,
            sequence=sequence,
            actor_id=actor,
            member_id=member,
            operation_key=str(event_id),
            action=action,
            payload_hash="a" * 64,
            payload={"reason": "Synthetic reviewed tariff"},
            result={"event_id": str(event_id)},
            recorded_at=datetime.now(timezone.utc),
            tariff_version=str(event_id) if action == "publish" else None,
        )
    )
    return event_id


def test_commercial_metadata_rechecks_current_subscription_authority(
    commercial_connection,
):
    connection = commercial_connection
    admin = _user(connection, admin=True)
    member = _user(connection)
    event_id = _subscription(connection, admin, member, 1)
    with (
        pytest.raises(DBAPIError, match="subscription_current_authority"),
        connection.begin_nested(),
    ):
        _subscription(connection, member, member, 2)
    connection.execute(
        UserModel.__table__.update()
        .where(UserModel.user_id == admin)
        .values(admin=False)
    )
    with (
        pytest.raises(DBAPIError, match="subscription_current_authority"),
        connection.begin_nested(),
    ):
        _subscription(connection, admin, member, 2)
    _subscription(connection, member, member, 2, "cancel")
    with (
        pytest.raises(DBAPIError, match="subscription_cancel_ownership"),
        connection.begin_nested(),
    ):
        _subscription(connection, admin, member, 3, "cancel")
    connection.execute(
        UserModel.__table__.update()
        .where(UserModel.user_id == member)
        .values(status="blocked")
    )
    with (
        pytest.raises(DBAPIError, match="subscription_current_authority"),
        connection.begin_nested(),
    ):
        _subscription(connection, member, member, 3, "cancel")
    assert (
        connection.scalar(
            text(
                "SELECT event_id FROM manager_subscription_events "
                "WHERE event_id=:event_id"
            ),
            {"event_id": event_id},
        )
        == event_id
    )


def test_commercial_metadata_retains_all_three_append_only_journals(
    commercial_connection,
):
    connection = commercial_connection
    admin = _user(connection, admin=True)
    event_id = _subscription(connection, admin, admin, 1)
    correction_id = uuid4()
    connection.execute(
        BINDING_CORRECTIONS.insert().values(
            correction_id=correction_id,
            referred_id=uuid4(),
            previous_referrer_id=uuid4(),
            referrer_id=uuid4(),
            actor_id=admin,
            reason="Synthetic reviewed binding correction",
            corrected_at=datetime.now(timezone.utc),
            operation_key=str(correction_id),
            payload_hash="b" * 64,
            result={"correction_id": str(correction_id)},
        )
    )
    for table, key, error in (
        ("manager_subscription_events", "event_id", "subscription_fact"),
        ("referral_binding_corrections", "correction_id", "immutable"),
        ("accompaniment_lead_reviews", "review_id", "immutable"),
    ):
        # These are statement guards, including an empty lead-review queue.
        for statement in (
            f"UPDATE {table} SET {key}={key}",
            f"DELETE FROM {table}",
            f"TRUNCATE {table}",
        ):
            with (
                pytest.raises(DBAPIError, match=error),
                connection.begin_nested(),
            ):
                connection.execute(text(statement))
    assert (
        connection.scalar(
            text(
                "SELECT count(*) FROM manager_subscription_events "
                "WHERE event_id=:event_id"
            ),
            {"event_id": event_id},
        )
        == 1
    )
    assert (
        connection.scalar(
            text(
                "SELECT count(*) FROM referral_binding_corrections "
                "WHERE correction_id=:correction_id"
            ),
            {"correction_id": correction_id},
        )
        == 1
    )
