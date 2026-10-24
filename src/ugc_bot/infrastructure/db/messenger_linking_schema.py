"""Frozen additive attach-only evidence and small replaceable projections."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

FACT_KEYS = (
    "challenges",
    "claims",
    "commands",
    "native_attempts",
    "native_results",
    "events",
)


def linking_tables(metadata):
    def uid(name, target=None, **kw):
        return sa.Column(
            name,
            UUID(as_uuid=True),
            *([sa.ForeignKey(target)] if target else []),
            **kw,
        )

    def dt(name):
        return sa.Column(name, sa.DateTime(timezone=True), nullable=False)

    def string(name, size=64, **kw):
        return sa.Column(name, sa.String(size), **kw)

    def payload(name):
        return sa.Column(
            name, sa.JSON().with_variant(JSONB(), "postgresql"), nullable=False
        )

    challenges = sa.Table(
        "messenger_link_challenges",
        metadata,
        uid("challenge_id", primary_key=True),
        uid("owner_id", "users.user_id", nullable=False),
        string("max_id", nullable=False),
        payload("context"),
        string("verifier", nullable=False, unique=True),
        dt("issued_at"),
        dt("expires_at"),
        sa.CheckConstraint(
            "expires_at=issued_at+interval '10 minutes'",
            name="ck_messenger_link_ttl",
        ),
    )
    claims = sa.Table(
        "messenger_link_claims",
        metadata,
        uid("claim_id", primary_key=True),
        uid(
            "challenge_id",
            "messenger_link_challenges.challenge_id",
            nullable=False,
            unique=True,
        ),
        string("telegram_id", nullable=False),
        payload("identity"),
        dt("observed_at"),
    )
    state = sa.Table(
        "messenger_link_state",
        metadata,
        uid(
            "challenge_id",
            "messenger_link_challenges.challenge_id",
            primary_key=True,
        ),
        string("state", 24, nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        uid("claim_id", "messenger_link_claims.claim_id"),
        sa.CheckConstraint("version>0", name="ck_messenger_link_version"),
    )
    active_owner = sa.Table(
        "messenger_link_active_owner",
        metadata,
        uid("owner_id", "users.user_id", primary_key=True),
        uid(
            "challenge_id",
            "messenger_link_challenges.challenge_id",
            nullable=False,
            unique=True,
        ),
    )
    active_tg = sa.Table(
        "messenger_link_active_telegram",
        metadata,
        string("telegram_id", primary_key=True),
        uid(
            "challenge_id",
            "messenger_link_challenges.challenge_id",
            nullable=False,
        ),
    )
    commands = sa.Table(
        "messenger_link_commands",
        metadata,
        uid("command_id", primary_key=True),
        uid("owner_id", "users.user_id", nullable=False),
        string("operation_key", 256, nullable=False),
        string("payload_hash", nullable=False),
        payload("receipt"),
        dt("recorded_at"),
        sa.UniqueConstraint(
            "owner_id", "operation_key", name="uq_messenger_link_operation"
        ),
    )
    native_attempts = sa.Table(
        "messenger_link_native_attempts",
        metadata,
        uid("source_id", primary_key=True),
        sa.Column("bot_id", sa.BigInteger, nullable=False),
        string("sender_id", nullable=False),
        string("update_id", nullable=False),
        string("payload_hash", nullable=False),
        dt("observed_at"),
        sa.UniqueConstraint(
            "bot_id", "update_id", name="uq_messenger_link_native_source"
        ),
    )
    native_results = sa.Table(
        "messenger_link_native_results",
        metadata,
        uid("result_id", primary_key=True),
        uid(
            "source_id",
            "messenger_link_native_attempts.source_id",
            nullable=False,
        ),
        string("payload_hash", nullable=False),
        payload("receipt"),
        dt("observed_at"),
        sa.UniqueConstraint(
            "source_id", "payload_hash", name="uq_messenger_link_native_result"
        ),
    )
    events = sa.Table(
        "messenger_link_events",
        metadata,
        uid("event_id", primary_key=True),
        uid("challenge_id", "messenger_link_challenges.challenge_id"),
        string("kind", 32, nullable=False),
        payload("fact"),
        dt("observed_at"),
    )
    sa.Index(
        "ix_messenger_link_native_quota",
        native_attempts.c.bot_id,
        native_attempts.c.sender_id,
        native_attempts.c.observed_at,
    )
    sa.Index(
        "ix_messenger_link_owner_quota",
        challenges.c.owner_id,
        challenges.c.issued_at,
    )
    return dict(
        challenges=challenges,
        claims=claims,
        state=state,
        active_owner=active_owner,
        active_tg=active_tg,
        commands=commands,
        native_attempts=native_attempts,
        native_results=native_results,
        events=events,
    )


def immutability_sql(tables):
    return """
CREATE FUNCTION messenger_link_deny_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
 RAISE EXCEPTION 'messenger_link_evidence_immutable' USING ERRCODE='23514';
END $$;
""" + "\n".join(
        f"CREATE TRIGGER {tables[key].name}_immutable "
        f"BEFORE UPDATE OR DELETE OR TRUNCATE ON {tables[key].name} "
        "FOR EACH STATEMENT EXECUTE FUNCTION messenger_link_deny_mutation();"
        for key in FACT_KEYS
    )
