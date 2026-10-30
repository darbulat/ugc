"""Append-only selection closure and item-specific maturity source facts."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


def selection_maturity_tables(metadata, *, per_item=False):
    json = sa.JSON().with_variant(JSONB(), "postgresql")
    closures = sa.Table(
        "financial_selection_closures",
        metadata,
        sa.Column("closure_id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "order_id",
            UUID(as_uuid=True),
            sa.ForeignKey("orders.order_id"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "client_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.user_id"),
            nullable=False,
        ),
        sa.Column(
            "payment_id",
            UUID(as_uuid=True),
            sa.ForeignKey("payments.payment_id"),
            nullable=False,
        ),
        sa.Column(
            "policy_version",
            sa.String,
            sa.ForeignKey("financial_policy_versions.version"),
            nullable=False,
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_document", json, nullable=False),
        sa.Column(
            "actor_id", UUID(as_uuid=True), sa.ForeignKey("users.user_id")
        ),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("evidence", sa.Text, nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "closed_at<=recorded_at", name="ck_selection_closure_chronology"
        ),
    )
    schedules = sa.Table(
        "financial_selection_schedules",
        metadata,
        sa.Column("source_id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "closure_id",
            UUID(as_uuid=True),
            sa.ForeignKey("financial_selection_closures.closure_id"),
            nullable=per_item,
        ),
        sa.Column(
            "paid_item_id",
            UUID(as_uuid=True),
            sa.ForeignKey("order_items.paid_item_id"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "order_id",
            UUID(as_uuid=True),
            sa.ForeignKey("orders.order_id"),
            nullable=False,
        ),
        sa.Column(
            "payment_id",
            UUID(as_uuid=True),
            sa.ForeignKey("payments.payment_id"),
            nullable=False,
        ),
        sa.Column(
            "client_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.user_id"),
            nullable=False,
        ),
        sa.Column(
            "policy_version",
            sa.String,
            sa.ForeignKey("financial_policy_versions.version"),
            nullable=False,
        ),
        sa.Column(
            "refund_deadline_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column(
            "hold_started_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column("release_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "hold_started_at>=refund_deadline_at "
            "AND release_at>hold_started_at",
            name="ck_selection_maturity_chronology",
        ),
        sa.CheckConstraint(
            (
                "(closure_id IS NOT NULL AND "
                "release_at=hold_started_at+INTERVAL '14 days') OR "
                "(closure_id IS NULL AND "
                "release_at=hold_started_at+1209600*INTERVAL '1 second')"
                if per_item
                else "release_at=hold_started_at+INTERVAL '14 days'"
            ),
            name="ck_selection_maturity_hold",
        ).ddl_if(dialect="postgresql"),
    )
    return {"closures": closures, "schedules": schedules}


def selection_maturity_guards(tables, *, per_item=False):
    statements = [
        """
CREATE OR REPLACE FUNCTION financial_selection_deny_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
 RAISE EXCEPTION 'financial_selection_fact_immutable' USING ERRCODE='23514';
END $$;
""",
        PER_ITEM_SELECTION_SOURCE_GUARD if per_item else SELECTION_SOURCE_GUARD,
    ]
    for table in tables.values():
        statements.append(
            "CREATE TRIGGER selection_fact_immutable BEFORE UPDATE OR "
            f"DELETE OR TRUNCATE ON {table.name} FOR EACH STATEMENT "
            "EXECUTE FUNCTION financial_selection_deny_mutation();"
        )
    for table in tables.values():
        statements.append(
            "CREATE TRIGGER selection_source_guard BEFORE INSERT ON "
            f"{table.name} FOR EACH ROW EXECUTE FUNCTION "
            "financial_selection_check_source();"
        )
    return "\n".join(statements)


SELECTION_SOURCE_GUARD = """
CREATE OR REPLACE FUNCTION financial_selection_check_source() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE closure record; item record; actual_delivery record; rules jsonb;
 latest_resolution timestamptz; unresolved integer; expected_count integer;
 expected_deadline timestamptz; expected_hold timestamptz;
BEGIN
 SELECT p.rules->'refund_rules' INTO rules FROM orders o
 JOIN financial_policy_versions p ON p.version=o.financial_version
 JOIN payments payment ON payment.order_id=o.order_id
 WHERE o.order_id=NEW.order_id AND o.advertiser_id=NEW.client_id
 AND payment.payment_id=NEW.payment_id AND payment.paid_at IS NOT NULL
 AND o.financial_version=NEW.policy_version;
 IF rules IS NULL THEN RAISE EXCEPTION 'selection_closure_scope_mismatch'
USING ERRCODE='23514'; END
IF;
 IF TG_TABLE_NAME='financial_selection_closures' THEN
   IF NEW.source_document->'refund_rules' IS DISTINCT FROM rules
   OR jsonb_typeof(NEW.source_document->'positions') IS DISTINCT FROM 'array'
   THEN RAISE EXCEPTION 'selection_closure_rules_mismatch' USING
ERRCODE='23514'; END IF;
   WITH resolved AS (
    SELECT i.paid_item_id, d.delivery_id, d.accepted_at AS delivered_at,
     r.refunded_at, r.application_id,
     COALESCE(d.accepted_at,r.refunded_at) AS resolved_at
    FROM order_items i LEFT JOIN paid_selection_accepted_deliveries d
     ON d.paid_item_id=i.paid_item_id AND d.payment_id=NEW.payment_id
    LEFT JOIN LATERAL (
     SELECT max(a.recorded_at) AS refunded_at,
      (array_agg(a.application_id ORDER BY a.recorded_at DESC))[1] AS
application_id
     FROM financial_refund_component_applications c
     JOIN financial_refund_applications a USING(application_id)
     WHERE c.paid_item_id=i.paid_item_id AND c.payment_id=NEW.payment_id
      AND c.component='selection' HAVING sum(c.refund_minor)=i.selection_minor
    ) r ON true WHERE i.order_id=NEW.order_id
   ) SELECT count(*),count(*) FILTER(WHERE resolved_at IS
NULL),max(resolved_at)
     INTO expected_count,unresolved,latest_resolution FROM resolved;
   IF expected_count=0 OR unresolved>0 OR latest_resolution>NEW.closed_at
   OR jsonb_array_length(NEW.source_document->'positions')<>expected_count
   OR EXISTS(SELECT 1 FROM order_items i WHERE i.order_id=NEW.order_id AND
    (i.policy_version<>NEW.policy_version
     OR i.quote_payload->'refund_rules' IS DISTINCT FROM rules
     OR NOT EXISTS(SELECT 1 FROM
jsonb_array_elements(NEW.source_document->'positions') v
      WHERE v->>'paid_item_id'=i.paid_item_id::text)))
   THEN RAISE EXCEPTION 'selection_actual_resolution_required' USING
ERRCODE='23514'; END IF;
   IF rules->>'selection_closure_mode'='all_positions_resolved' THEN
    IF NEW.closed_at<>latest_resolution THEN
     RAISE EXCEPTION 'selection_closure_time_mismatch' USING
ERRCODE='23514'; END IF;
   ELSIF rules->>'selection_closure_mode'='manual' THEN
    IF NEW.actor_id IS NULL OR length(trim(NEW.reason))=0
     OR length(trim(NEW.evidence))=0 OR NOT EXISTS(
      SELECT 1 FROM users u WHERE u.user_id=NEW.actor_id AND
       ((u.admin AND u.status='active') OR
        (u.user_id=NEW.client_id AND u.status IN
('active','pause','bot_blocked')
         AND EXISTS(SELECT 1 FROM advertiser_profiles a WHERE
a.user_id=u.user_id))))
    THEN RAISE EXCEPTION 'selection_manual_closure_authority_required' USING
ERRCODE='23514'; END
IF;
   ELSE RAISE EXCEPTION 'selection_closure_rules_mismatch' USING
ERRCODE='23514'; END IF;
 ELSE
   SELECT * INTO closure FROM financial_selection_closures
    WHERE closure_id=NEW.closure_id;
   SELECT * INTO item FROM order_items WHERE paid_item_id=NEW.paid_item_id;
   SELECT * INTO actual_delivery FROM paid_selection_accepted_deliveries
    WHERE paid_item_id=NEW.paid_item_id AND payment_id=NEW.payment_id;
   IF closure.closure_id IS NULL OR actual_delivery.delivery_id IS NULL
    OR
(closure.order_id,closure.payment_id,closure.client_id,closure.policy_version)
    IS DISTINCT FROM
(NEW.order_id,NEW.payment_id,NEW.client_id,NEW.policy_version)
    OR item.order_id IS DISTINCT FROM NEW.order_id
    OR EXISTS(SELECT 1 FROM financial_refund_component_applications
      WHERE paid_item_id=NEW.paid_item_id AND component='selection')
   THEN RAISE EXCEPTION 'selection_schedule_source_mismatch' USING
ERRCODE='23514'; END IF;
   IF rules->>'selection_refund_window_anchor'='item_delivered' THEN
    expected_deadline:=actual_delivery.accepted_at;
   ELSIF rules->>'selection_refund_window_anchor'='order_closed' THEN
    expected_deadline:=closure.closed_at;
   ELSE RAISE EXCEPTION 'selection_closure_rules_mismatch' USING
ERRCODE='23514'; END IF;
   expected_deadline:=expected_deadline+
    (rules->>'selection_refund_window_seconds')::bigint*INTERVAL '1 second';
   expected_hold:=GREATEST(expected_deadline,closure.closed_at);
   IF NEW.refund_deadline_at<>expected_deadline OR
NEW.hold_started_at<>expected_hold
    OR NEW.release_at<>expected_hold+INTERVAL '14 days'
   THEN RAISE EXCEPTION 'selection_schedule_time_mismatch' USING
ERRCODE='23514'; END IF;
 END IF;
 RETURN NEW;
END $$;
"""


# The earlier revision imports this module, so retain its original DDL and
# explicitly opt into the new guard only in the current model and migration.
_PER_ITEM_GUARD_PREFIX = """
 IF TG_TABLE_NAME='financial_selection_schedules' AND EXISTS (
  SELECT 1 FROM financial_policy_versions p
  WHERE p.version=NEW.policy_version
   AND p.rules->>'maturity_mode'='per_item_v1'
 ) THEN
  SELECT d.* INTO actual_delivery
  FROM paid_selection_accepted_deliveries d
  JOIN order_items i ON i.paid_item_id=d.paid_item_id
  JOIN orders o ON o.order_id=i.order_id
  JOIN payments payment ON payment.payment_id=d.payment_id
  JOIN financial_policy_versions p ON p.version=o.financial_version
  WHERE d.paid_item_id=NEW.paid_item_id
   AND d.order_id=NEW.order_id AND d.client_id=NEW.client_id
   AND d.payment_id=NEW.payment_id
   AND i.order_id=NEW.order_id AND i.policy_version=NEW.policy_version
   AND o.advertiser_id=NEW.client_id AND o.financial_version=NEW.policy_version
   AND payment.order_id=NEW.order_id AND payment.paid_at IS NOT NULL
   AND i.captured_at=payment.paid_at
   AND i.quote_payload->>'terms_reference'=p.rules->>'terms_reference'
   AND (NOT (p.rules ? 'refund_rules') OR
        (i.quote_payload->'refund_rules'=p.rules->'refund_rules'
        AND p.rules->'refund_rules'->>'selection_refund_window_anchor'=
            'item_delivered'
        AND p.rules->'refund_rules'->>'selection_refund_window_seconds'=
            '604800'))
   AND p.refund_window_seconds=604800
   AND p.rules->>'hold_seconds'='1209600'
   AND p.rules->>'selection_refund_window_anchor'=
       'per_item_delivery_accepted_at';
  IF actual_delivery.delivery_id IS NULL OR NEW.closure_id IS NOT NULL
   OR EXISTS(SELECT 1 FROM financial_refund_component_applications
     WHERE paid_item_id=NEW.paid_item_id AND component='selection')
  THEN RAISE EXCEPTION 'selection_schedule_source_mismatch'
   USING ERRCODE='23514'; END IF;
  expected_deadline:=actual_delivery.accepted_at+604800*INTERVAL '1 second';
  IF NEW.refund_deadline_at<>expected_deadline
   OR NEW.hold_started_at<>expected_deadline
   OR NEW.release_at<>expected_deadline+1209600*INTERVAL '1 second'
  THEN RAISE EXCEPTION 'selection_schedule_time_mismatch'
   USING ERRCODE='23514'; END IF;
  RETURN NEW;
 END IF;
"""
PER_ITEM_SELECTION_SOURCE_GUARD = SELECTION_SOURCE_GUARD.replace(
    "BEGIN\n SELECT p.rules",
    "BEGIN\n" + _PER_ITEM_GUARD_PREFIX + " SELECT p.rules",
    1,
)
