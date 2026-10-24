"""Frozen financial_payout_v1 DDL; future revisions extend separately."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

NAMES = (
    "financial_payout_commands",
    "financial_payout_requirements",
    "financial_payout_requisites",
    "financial_payout_requests",
    "financial_payout_allocations",
    "financial_payout_events",
    "financial_payout_intents",
    "financial_payout_outcomes",
    "financial_payout_settlements",
    "financial_payout_states",
    "financial_payout_movement_links",
)


def payout_tables(metadata):
    obligations = metadata.tables["financial_obligations"]
    if not any(
        c.name == "uq_payout_obligation_owner" for c in obligations.constraints
    ):
        obligations.append_constraint(
            sa.UniqueConstraint(
                "id",
                "recipient_id",
                "currency",
                name="uq_payout_obligation_owner",
            )
        )

    def uid(name, target=None, **kw):
        return sa.Column(
            name,
            UUID(as_uuid=True),
            *([sa.ForeignKey(target)] if target else []),
            **kw,
        )

    def col(name, type_=sa.Text, **kw):
        return sa.Column(name, type_, nullable=False, **kw)

    def at(name):
        return col(name, sa.DateTime(timezone=True))

    def obj(name):
        return col(name, sa.JSON().with_variant(JSONB(), "postgresql"))

    def money():
        return (
            col("amount_minor", sa.BigInteger),
            col("currency", sa.String(3)),
            sa.CheckConstraint("amount_minor>0 AND currency='RUB'"),
        )

    def table(name, *columns):
        return sa.Table("financial_payout_" + name, metadata, *columns)

    t = {}
    t["commands"] = table(
        "commands",
        uid("command_id", primary_key=True),
        uid("actor_id", "users.user_id", nullable=False),
        col("operation_key", sa.String(256)),
        col("action", sa.String(40)),
        col("payload_hash", sa.String(64)),
        at("recorded_at"),
        obj("result"),
        sa.UniqueConstraint("actor_id", "operation_key"),
        sa.CheckConstraint(
            "length(trim(operation_key))>0 AND length(payload_hash)=64"
        ),
    )
    t["requirements"] = table(
        "requirements",
        uid("requirements_id", primary_key=True),
        col("version", sa.Integer, unique=True),
        uid("actor_id", "users.user_id", nullable=False),
        at("recorded_at"),
        at("effective_from"),
        col("legal_reference"),
        col("terms_reference"),
        col("evidence_reference"),
        col("reason"),
        obj("required_fields"),
        col("enabled", sa.Boolean),
        sa.CheckConstraint(
            "version>0 AND effective_from>=recorded_at AND "
            "length(trim(legal_reference))>0 AND "
            "length(trim(terms_reference))>0 AND "
            "length(trim(evidence_reference))>0 AND length(trim(reason))>0"
        ),
    )
    t["requisites"] = table(
        "requisites",
        uid("requisites_id", primary_key=True),
        uid("recipient_id", "users.user_id", nullable=False),
        uid(
            "requirements_id",
            "financial_payout_requirements.requirements_id",
            nullable=False,
        ),
        col("key_id", sa.String(64)),
        col("ciphertext", sa.LargeBinary),
        col("fingerprint", sa.String(64)),
        col("masked_label", sa.String(200)),
        at("recorded_at"),
        sa.UniqueConstraint("requisites_id", "recipient_id", "requirements_id"),
        sa.CheckConstraint(
            "length(ciphertext)>28 AND length(fingerprint)=64 AND "
            "length(trim(key_id))>0"
        ),
    )
    t["requests"] = table(
        "requests",
        uid("request_id", "payout_requests.request_id", primary_key=True),
        uid("recipient_id", "users.user_id", nullable=False),
        *money(),
        uid("requisites_id", nullable=False),
        uid("requirements_id", nullable=False),
        at("requested_at"),
        at("deadline_at"),
        sa.UniqueConstraint("request_id", "recipient_id", "currency"),
        sa.UniqueConstraint("request_id", "amount_minor", "currency"),
        sa.ForeignKeyConstraint(
            ("requisites_id", "recipient_id", "requirements_id"),
            (
                "financial_payout_requisites.requisites_id",
                "financial_payout_requisites.recipient_id",
                "financial_payout_requisites.requirements_id",
            ),
        ),
        sa.CheckConstraint("deadline_at=requested_at+interval '72 hours'"),
    )
    t["allocations"] = table(
        "allocations",
        uid("allocation_id", primary_key=True),
        uid("request_id", nullable=False),
        uid("obligation_id", nullable=False),
        uid("recipient_id", nullable=False),
        *money(),
        sa.UniqueConstraint("request_id", "obligation_id"),
        sa.UniqueConstraint(
            "allocation_id", "request_id", "obligation_id", "currency"
        ),
        sa.ForeignKeyConstraint(
            ("request_id", "recipient_id", "currency"),
            (
                "financial_payout_requests.request_id",
                "financial_payout_requests.recipient_id",
                "financial_payout_requests.currency",
            ),
        ),
        sa.ForeignKeyConstraint(
            ("obligation_id", "recipient_id", "currency"),
            (
                "financial_obligations.id",
                "financial_obligations.recipient_id",
                "financial_obligations.currency",
            ),
        ),
    )
    t["events"] = table(
        "events",
        uid("event_id", primary_key=True),
        uid(
            "request_id", "financial_payout_requests.request_id", nullable=False
        ),
        col("version", sa.Integer),
        col("action", sa.String(40)),
        col("state", sa.String(40)),
        uid("actor_id", "users.user_id", nullable=False),
        col("reason"),
        at("recorded_at"),
        obj("details"),
        sa.UniqueConstraint("request_id", "version"),
        sa.CheckConstraint("version>0 AND length(trim(reason))>0"),
    )
    t["intents"] = table(
        "intents",
        uid("execution_id", primary_key=True),
        uid(
            "request_id", "financial_payout_requests.request_id", nullable=False
        ),
        uid("actor_id", "users.user_id", nullable=False),
        uid("fence", nullable=False, unique=True),
        *money(),
        col("fingerprint", sa.String(64)),
        col("bank_account", sa.String(256)),
        at("prepared_at"),
        sa.CheckConstraint("length(trim(bank_account))>0"),
        sa.UniqueConstraint("execution_id", "request_id", "currency"),
        sa.UniqueConstraint("execution_id", "request_id"),
        sa.UniqueConstraint(
            "execution_id", "request_id", "amount_minor", "currency"
        ),
        sa.ForeignKeyConstraint(
            ("request_id", "amount_minor", "currency"),
            (
                "financial_payout_requests.request_id",
                "financial_payout_requests.amount_minor",
                "financial_payout_requests.currency",
            ),
        ),
    )
    t["outcomes"] = table(
        "outcomes",
        uid("outcome_id", primary_key=True),
        uid(
            "execution_id",
            "financial_payout_intents.execution_id",
            nullable=False,
        ),
        uid(
            "request_id", "financial_payout_requests.request_id", nullable=False
        ),
        uid("actor_id", "users.user_id", nullable=False),
        col("status", sa.String(20)),
        sa.Column("amount_minor", sa.BigInteger),
        sa.Column("currency", sa.String(20)),
        sa.Column("settled_at", sa.DateTime(timezone=True)),
        col("bank_account", sa.String(256)),
        col("bank_reference", sa.String(256)),
        col("evidence_reference"),
        col("evidence_hash", sa.String(64)),
        col("fingerprint", sa.String(64)),
        col("key_id", sa.String(64)),
        col("ciphertext", sa.LargeBinary),
        at("recorded_at"),
        col("applied", sa.Boolean),
        col("review_reason", sa.String(100)),
        sa.ForeignKeyConstraint(
            ("execution_id", "request_id"),
            (
                "financial_payout_intents.execution_id",
                "financial_payout_intents.request_id",
            ),
        ),
        sa.CheckConstraint(
            "status IN ('paid','failed','unknown') AND "
            "length(trim(evidence_reference))>0 AND "
            "length(evidence_hash)=64 AND (NOT applied OR (status='paid' "
            "AND amount_minor IS NOT NULL AND amount_minor>0 AND currency "
            "IS NOT NULL AND currency='RUB' AND settled_at IS NOT NULL "
            "AND length(trim(bank_account))>0 AND "
            "length(trim(bank_reference))>0))"
        ),
    )
    t["settlements"] = table(
        "settlements",
        uid(
            "execution_id",
            "financial_payout_intents.execution_id",
            primary_key=True,
        ),
        uid(
            "request_id",
            "financial_payout_requests.request_id",
            nullable=False,
            unique=True,
        ),
        uid(
            "outcome_id",
            "financial_payout_outcomes.outcome_id",
            nullable=False,
            unique=True,
        ),
        *money(),
        col("bank_account", sa.String(256)),
        col("bank_reference", sa.String(256)),
        at("settled_at"),
        sa.UniqueConstraint("bank_account", "bank_reference"),
        sa.UniqueConstraint("execution_id", "request_id", "currency"),
        sa.ForeignKeyConstraint(
            ("execution_id", "request_id", "amount_minor", "currency"),
            (
                "financial_payout_intents.execution_id",
                "financial_payout_intents.request_id",
                "financial_payout_intents.amount_minor",
                "financial_payout_intents.currency",
            ),
        ),
        sa.CheckConstraint(
            "length(trim(bank_account))>0 AND length(trim(bank_reference))>0"
        ),
    )
    t["states"] = table(
        "states",
        uid(
            "request_id",
            "financial_payout_requests.request_id",
            primary_key=True,
        ),
        col("version", sa.Integer),
        col("state", sa.String(40)),
        sa.Column(
            "execution_id",
            UUID(as_uuid=True),
            sa.ForeignKey("financial_payout_intents.execution_id"),
        ),
        col("block_reason", sa.String(100)),
        sa.CheckConstraint(
            "version>0 AND state IN "
            "('reserved','approved','blocked','executing','unknown','failed','paid','rejected')"
        ),
    )
    t["movement_links"] = table(
        "movement_links",
        uid("movement_id", "financial_movements.id", primary_key=True),
        uid("request_id", nullable=False),
        uid("allocation_id", nullable=False),
        uid("obligation_id", nullable=False),
        *money(),
        sa.Column("execution_id", UUID(as_uuid=True)),
        sa.ForeignKeyConstraint(
            ("allocation_id", "request_id", "obligation_id", "currency"),
            (
                "financial_payout_allocations.allocation_id",
                "financial_payout_allocations.request_id",
                "financial_payout_allocations.obligation_id",
                "financial_payout_allocations.currency",
            ),
        ),
        sa.ForeignKeyConstraint(
            ("execution_id", "request_id", "currency"),
            (
                "financial_payout_settlements.execution_id",
                "financial_payout_settlements.request_id",
                "financial_payout_settlements.currency",
            ),
        ),
    )
    return t


IMMUTABILITY_SQL = """
CREATE OR REPLACE FUNCTION payout_deny_mutation() RETURNS trigger LANGUAGE
plpgsql AS $$
BEGIN RAISE EXCEPTION 'payout_fact_immutable' USING ERRCODE='23514'; END $$;
"""
GUARD_SQL = """
CREATE FUNCTION payout_guard_anchor() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF OLD.payout_protocol IS NOT NULL THEN
  RAISE EXCEPTION 'payout_anchor_immutable' USING ERRCODE='23514';
 END IF;
 IF TG_OP='UPDATE' AND NEW.payout_protocol IS DISTINCT FROM
OLD.payout_protocol THEN
  RAISE EXCEPTION 'legacy_payout_cannot_convert' USING ERRCODE='23514';
 END IF;
 IF TG_OP='DELETE' THEN RETURN OLD; END IF; RETURN NEW;
END $$;
CREATE TRIGGER payout_anchor_guard BEFORE UPDATE OR DELETE ON
payout_requests
FOR EACH ROW EXECUTE FUNCTION payout_guard_anchor();
CREATE FUNCTION payout_check_movement() RETURNS trigger LANGUAGE plpgsql AS
$$
DECLARE protocol text; link financial_payout_movement_links; alloc
financial_payout_allocations;
BEGIN
 SELECT payout_protocol INTO protocol FROM payout_requests WHERE
request_id=NEW.request_id;
 IF protocol IS DISTINCT FROM 'financial_v1' THEN RETURN NEW; END IF;
 SELECT * INTO link FROM financial_payout_movement_links WHERE
movement_id=NEW.id;
 SELECT * INTO alloc FROM financial_payout_allocations WHERE
allocation_id=NEW.allocation_id;
 IF link.movement_id IS NULL OR alloc.allocation_id IS NULL OR
 (link.request_id, link.allocation_id, link.obligation_id, link.currency,
link.amount_minor, link.execution_id)
 IS DISTINCT FROM (NEW.request_id, NEW.allocation_id, NEW.obligation_id,
NEW.currency, NEW.amount_minor, NEW.execution_id)
 OR alloc.request_id<>NEW.request_id OR
alloc.obligation_id<>NEW.obligation_id OR
NEW.amount_minor>alloc.amount_minor
 OR NEW.movement_type<>'transfer' OR NOT (
 (NEW.bucket_from='available' AND NEW.bucket_to='reserved' AND
NEW.execution_id IS NULL) OR
 (NEW.bucket_from='reserved' AND NEW.bucket_to IN ('available', 'blocked')
AND NEW.execution_id IS NULL) OR
 (NEW.bucket_from='reserved' AND NEW.bucket_to='paid' AND NEW.execution_id
IS NOT NULL)) THEN
  RAISE EXCEPTION 'payout_movement_scope_invalid' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE CONSTRAINT TRIGGER payout_movement_guard AFTER INSERT ON
financial_movements
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION
payout_check_movement();
"""

SCOPE_GUARD_SQL = """
CREATE FUNCTION payout_check_request_anchor() RETURNS trigger LANGUAGE
plpgsql AS $$
DECLARE anchor payout_requests;
BEGIN
 SELECT * INTO anchor FROM payout_requests WHERE request_id=NEW.request_id;
 IF anchor.payout_protocol IS DISTINCT FROM 'financial_v1' OR
 anchor.amount IS NOT NULL OR
 (anchor.user_id, anchor.currency, anchor.requested_at, anchor.status::text)
 IS DISTINCT FROM
 (NEW.recipient_id, NEW.currency, NEW.requested_at, 'pending') THEN
  RAISE EXCEPTION 'payout_request_anchor_invalid' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER payout_request_anchor_scope BEFORE INSERT ON
financial_payout_requests
FOR EACH ROW EXECUTE FUNCTION payout_check_request_anchor();
CREATE FUNCTION payout_check_settlement() RETURNS trigger LANGUAGE plpgsql
AS $$
DECLARE outcome financial_payout_outcomes; intent financial_payout_intents;
BEGIN
 SELECT * INTO outcome FROM financial_payout_outcomes WHERE
outcome_id=NEW.outcome_id;
 SELECT * INTO intent FROM financial_payout_intents WHERE
execution_id=NEW.execution_id;
 IF outcome.outcome_id IS NULL OR NOT outcome.applied OR
outcome.status<>'paid' OR
 (NEW.execution_id, NEW.request_id, NEW.amount_minor, NEW.currency,
NEW.bank_account, NEW.bank_reference, NEW.settled_at)
 IS DISTINCT FROM
 (outcome.execution_id, outcome.request_id, outcome.amount_minor,
outcome.currency, outcome.bank_account, outcome.bank_reference,
outcome.settled_at)
 OR (NEW.request_id, NEW.amount_minor, NEW.currency) IS DISTINCT FROM
 (intent.request_id, intent.amount_minor, intent.currency) THEN
  RAISE EXCEPTION 'payout_settlement_proof_invalid' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER payout_settlement_scope BEFORE INSERT ON
financial_payout_settlements
FOR EACH ROW EXECUTE FUNCTION payout_check_settlement();
"""
