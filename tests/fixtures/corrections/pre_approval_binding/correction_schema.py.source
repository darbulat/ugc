"""Additive immutable correction facts and deferred full-bundle invariants."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

PREFIX = "financial_"


def _non_nil_constraints(tables):
    for key, table in tables.items():
        for column in table.c:
            if isinstance(column.type, UUID):
                table.append_constraint(
                    sa.CheckConstraint(
                        f"{column.name} IS NULL OR {column.name}<>"
                        "'00000000-0000-0000-0000-000000000000'",
                        name=f"ck_correction_{key}_{column.name}",
                    )
                )


def correction_tables(metadata):
    json_type = sa.JSON().with_variant(JSONB(), "postgresql")

    def uid(name, target=None, *, nullable=False, primary_key=False):
        return sa.Column(
            name,
            UUID(as_uuid=True),
            *(
                [sa.ForeignKey(target, deferrable=True, initially="DEFERRED")]
                if target
                else []
            ),
            nullable=nullable,
            primary_key=primary_key,
        )

    def col(name, kind=sa.Text, *, nullable=False):
        return sa.Column(name, kind, nullable=nullable)

    def at(name="recorded_at", *, nullable=False):
        return col(name, sa.DateTime(timezone=True), nullable=nullable)

    def command():
        return uid("command_id", "financial_correction_commands.command_id")

    def case(*, nullable=False):
        return uid(
            "case_id", "financial_correction_cases.case_id", nullable=nullable
        )

    def check(value, name):
        return sa.CheckConstraint(value, name="ck_correction_" + name)

    tables = {}

    def table(key, name, *columns):
        result = sa.Table(PREFIX + name, metadata, *columns)
        tables[key] = result
        return result

    table(
        "commands",
        "correction_commands",
        uid("command_id", primary_key=True),
        uid("actor_id", "users.user_id"),
        col("operation_key", sa.String(256)),
        col("action", sa.String(64)),
        col("payload_hash", sa.String(64)),
        at(),
        col("result", json_type),
        sa.UniqueConstraint("actor_id", "operation_key"),
        check(
            "length(trim(operation_key))>0 AND payload_hash ~ '^[0-9a-f]{64}$'",
            "command",
        ),
    )
    table(
        "cases",
        "correction_cases",
        uid("case_id", primary_key=True),
        command(),
        uid("client_id", "users.user_id", nullable=True),
        uid("order_id", "orders.order_id", nullable=True),
        at(),
    )
    table(
        "events",
        "correction_events",
        uid("event_id", primary_key=True),
        case(),
        col("version", sa.BigInteger),
        command(),
        uid("source_id"),
        uid("actor_id", "users.user_id"),
        col("reason"),
        col("evidence_reference"),
        col("evidence_hash", sa.String(64)),
        col("source_hash", sa.String(64)),
        col("previous_state_hash", sa.String(64), nullable=True),
        col("result_state_hash", sa.String(64)),
        col("result_state", json_type),
        at(),
        sa.UniqueConstraint("case_id", "version"),
        check(
            (
                "version>0 AND length(trim(reason))>0 AND evidence_hash ~ "
                "'^[0-9a-f]{64}$' AND source_hash ~ '^[0-9a-f]{64}$' AND "
                "result_state_hash ~ '^[0-9a-f]{64}$'"
            ),
            "event",
        ),
    )
    table(
        "requests",
        "correction_requests",
        uid("request_id", primary_key=True),
        case(),
        command(),
        uid("order_id", "orders.order_id"),
        uid("client_id", "users.user_id"),
        col("paid_item_ids", json_type),
        col("source_hash", sa.String(64)),
        col("bundle", json_type, nullable=True),
        at(),
        sa.UniqueConstraint("case_id"),
        check(
            (
                "jsonb_typeof(paid_item_ids)='array' AND "
                "jsonb_array_length(paid_item_ids) BETWEEN 1 AND 30"
            ),
            "request_items",
        ),
    )
    table(
        "intents",
        "refund_intents",
        uid("intent_id", primary_key=True),
        case(),
        command(),
        uid(
            "request_id",
            "financial_correction_requests.request_id",
            nullable=True,
        ),
        uid("capture_id", "outbox_events.event_id", nullable=True),
        uid("payment_id", "payments.payment_id", nullable=True),
        col("source_hash", sa.String(64), nullable=True),
        col("bundle", json_type, nullable=True),
        col("amount_minor", sa.BigInteger, nullable=True),
        col("currency", sa.String(3), nullable=True),
        col("review_version", sa.BigInteger, nullable=True),
        at(),
        check(
            (
                "(amount_minor IS NULL OR amount_minor>0) AND (currency IS "
                "NULL OR currency='RUB') AND (review_version IS NULL OR "
                "review_version>0)"
            ),
            "intent",
        ),
    )
    table(
        "observations",
        "refund_observations",
        uid("observation_id", primary_key=True),
        case(nullable=True),
        uid("intent_id", "financial_refund_intents.intent_id", nullable=True),
        command(),
        uid("known_order_id", nullable=True),
        uid("known_capture_intent_id", nullable=True),
        col("original_payment_reference"),
        col("bank_account_label"),
        col("bank_reference"),
        col("amount_minor", sa.BigInteger, nullable=True),
        col("currency", sa.String(64), nullable=True),
        at("occurred_at", nullable=True),
        col("reported_component", sa.String(30)),
        col("provenance", sa.String(40)),
        col("evidence_reference"),
        col("evidence_hash", sa.String(64)),
        at(),
        check(
            (
                "provenance='manual_admin_observation' AND "
                "reported_component IN "
                "('selection','accompaniment','management','replacement',"
                "'unknown') AND evidence_hash ~ '^[0-9a-f]{64}$'"
            ),
            "observation",
        ),
    )
    table(
        "matches",
        "refund_matches",
        uid("match_id", primary_key=True),
        case(),
        command(),
        uid("intent_id", "financial_refund_intents.intent_id"),
        uid("observation_id", "financial_refund_observations.observation_id"),
        uid("order_id", "orders.order_id"),
        uid("capture_id", "outbox_events.event_id"),
        uid("payment_id", "payments.payment_id"),
        col("source_hash", sa.String(64)),
        col("bundle", json_type),
        col("amount_minor", sa.BigInteger),
        col("currency", sa.String(3)),
        col("review_version", sa.BigInteger),
        at(),
        sa.UniqueConstraint("command_id"),
        check(
            (
                "amount_minor>0 AND currency='RUB' AND review_version>0 AND "
                "jsonb_typeof(bundle)='array' AND jsonb_array_length(bundle) "
                "BETWEEN 1 AND 30"
            ),
            "match",
        ),
    )
    table(
        "applications",
        "refund_applications",
        uid("application_id", primary_key=True),
        uid("match_id", "financial_refund_matches.match_id"),
        uid("intent_id", "financial_refund_intents.intent_id"),
        case(),
        uid("order_id", "orders.order_id"),
        uid("payment_id", "payments.payment_id"),
        uid("capture_id", "outbox_events.event_id"),
        col("source_hash", sa.String(64)),
        col("amount_minor", sa.BigInteger),
        col("currency", sa.String(3)),
        at(),
        sa.UniqueConstraint("match_id"),
        sa.UniqueConstraint("intent_id"),
        check("amount_minor>0 AND currency='RUB'", "application"),
    )
    table(
        "components",
        "refund_component_applications",
        uid("component_application_id", primary_key=True),
        uid("application_id", "financial_refund_applications.application_id"),
        col("allocation_key", sa.Text),
        uid("payment_id", "payments.payment_id"),
        uid("paid_item_id", "order_items.paid_item_id"),
        col("component", sa.String(20)),
        col("currency", sa.String(3)),
        col("gross_minor", sa.BigInteger),
        col("prior_refund_minor", sa.BigInteger),
        col("new_refund_minor", sa.BigInteger),
        col("refund_minor", sa.BigInteger),
        sa.ForeignKeyConstraint(
            ["allocation_key"], ["payment_item_allocations.allocation_key"]
        ),
        sa.UniqueConstraint("application_id", "allocation_key"),
        check(
            (
                "component='selection' AND currency='RUB' AND "
                "gross_minor=50000 AND prior_refund_minor>=0 AND "
                "new_refund_minor=prior_refund_minor+refund_minor AND "
                "new_refund_minor<=gross_minor AND refund_minor=gross_minor"
            ),
            "component",
        ),
    )
    table(
        "liabilities",
        "refund_liability_assessments",
        uid("assessment_id", primary_key=True),
        uid(
            "component_application_id",
            "financial_refund_component_applications.component_application_id",
        ),
        col("status", sa.String(30)),
        col("business_key"),
        uid("obligation_id", "financial_obligations.id", nullable=True),
        uid("snapshot_id", "rate_snapshots.id", nullable=True),
        uid("issuance_entry_id", "financial_movements.id", nullable=True),
        uid("potential_id", "financial_audit_events.id", nullable=True),
        col("frozen_rate_bps", sa.Integer, nullable=True),
        uid("override_id", nullable=True),
        col("target_minor", sa.BigInteger),
        col("already_cancelled_minor", sa.BigInteger),
        col("delta_minor", sa.BigInteger),
        uid("movement_id", "financial_movements.id", nullable=True),
        sa.UniqueConstraint("component_application_id"),
        sa.UniqueConstraint("movement_id"),
        check(
            (
                "status IN ('pending_cancelled','covered_absence') AND "
                "target_minor>=0 AND already_cancelled_minor>=0 AND "
                "delta_minor=target_minor-already_cancelled_minor AND "
                "delta_minor>=0 AND (frozen_rate_bps IS NULL OR "
                "frozen_rate_bps BETWEEN 0 AND 10000)"
            ),
            "liability",
        ),
    )
    table(
        "states",
        "correction_states",
        case(),
        uid("event_id", "financial_correction_events.event_id"),
        col("version", sa.BigInteger),
        col("result_state", json_type),
        col("result_state_hash", sa.String(64)),
        sa.PrimaryKeyConstraint("case_id"),
        check("version>0", "state"),
    )
    table(
        "proofs",
        "physical_proof_claims",
        uid("claim_id", primary_key=True),
        col("source", sa.String(256)),
        col("account", sa.String(256)),
        col("direction", sa.String(10)),
        col("reference"),
        col("key_hash", sa.String(64)),
        col("producer", sa.String(20)),
        uid("intent_id"),
        uid("observation_id"),
        uid("command_id"),
        at(),
        sa.UniqueConstraint("key_hash"),
        check(
            (
                "direction IN ('incoming','outgoing') AND producer IN "
                "('payout','refund','repayment') AND length(trim(source))>0 "
                "AND length(trim(account))>0 AND length(trim(reference))>0 "
                "AND key_hash ~ '^[0-9a-f]{64}$'"
            ),
            "proof",
        ),
    )
    _non_nil_constraints(tables)
    return tables


GUARD_SQL = """
CREATE OR REPLACE FUNCTION correction_deny_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
 RAISE EXCEPTION 'correction_fact_immutable' USING ERRCODE='23514';
END $$;

CREATE OR REPLACE FUNCTION correction_check_application() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE app record; matched record; intent record; request record;
 component record; liability record;
 allocation record; original record; snapshot record; issuance record;
 movement record; potential record; capture record; expected numeric;
 prior numeric; total numeric; n integer; expected_n integer; actual_pending
numeric;
BEGIN
 IF TG_TABLE_NAME='financial_refund_applications' THEN
   SELECT * INTO app FROM financial_refund_applications WHERE
application_id=NEW.application_id;
 ELSIF TG_TABLE_NAME='financial_refund_component_applications' THEN
   SELECT * INTO app FROM financial_refund_applications WHERE
application_id=NEW.application_id;
 ELSE
   SELECT a.* INTO app FROM financial_refund_applications a
   JOIN financial_refund_component_applications c USING(application_id)
   WHERE c.component_application_id=NEW.component_application_id;
 END IF;
 IF app.application_id IS NULL THEN RAISE EXCEPTION
'correction_application_missing'; END IF;
 SELECT * INTO matched FROM financial_refund_matches WHERE
match_id=app.match_id;
 SELECT * INTO intent FROM financial_refund_intents WHERE
intent_id=app.intent_id;
 SELECT * INTO request FROM financial_correction_requests WHERE
request_id=intent.request_id;
 IF (matched.intent_id,matched.case_id,matched.order_id,matched.payment_id,
matched.capture_id,matched.source_hash,matched.amount_minor,matched.currency)
 IS DISTINCT FROM (app.intent_id,app.case_id,app.order_id,app.payment_id,
     app.capture_id,app.source_hash,app.amount_minor,app.currency)
 OR NOT EXISTS (SELECT 1 FROM financial_refund_observations o WHERE
     o.observation_id=matched.observation_id AND o.intent_id=app.intent_id
     AND o.amount_minor=app.amount_minor AND o.currency='RUB') THEN
   RAISE EXCEPTION 'correction_application_source_mismatch';
 END IF;
 SELECT * INTO capture FROM outbox_events WHERE event_id=app.capture_id;
 IF capture.event_id IS NULL
   OR capture.event_type IS DISTINCT FROM
'financial.client_snapshot_requested'
   OR capture.aggregate_type IS DISTINCT FROM 'order'
   OR capture.aggregate_id IS DISTINCT FROM app.order_id::text
   OR capture.payload->>'payment_id' IS DISTINCT FROM app.payment_id::text
   OR capture.payload#>>'{capture,order_id}' IS DISTINCT FROM
app.order_id::text
   OR capture.payload#>>'{capture,client_id}' IS DISTINCT FROM
request.client_id::text
 THEN RAISE EXCEPTION 'correction_capture_source_mismatch'; END IF;
 IF intent.case_id IS DISTINCT FROM app.case_id
   OR request.case_id IS DISTINCT FROM app.case_id
   OR request.order_id IS DISTINCT FROM app.order_id
   OR intent.review_version IS NULL
   OR NOT EXISTS (SELECT 1 FROM financial_correction_events e
     WHERE e.case_id=app.case_id AND e.version=intent.review_version
       AND e.result_state->>'review_status'='approved')
   OR NOT EXISTS (SELECT 1 FROM orders o WHERE o.order_id=app.order_id
     AND o.advertiser_id=request.client_id)
   OR (SELECT jsonb_agg(x ORDER BY x) FROM
jsonb_array_elements_text(request.paid_item_ids) x)
      IS DISTINCT FROM (SELECT jsonb_agg(b->>'paid_item_id' ORDER BY
b->>'paid_item_id')
        FROM jsonb_array_elements(matched.bundle) b)
 THEN RAISE EXCEPTION 'correction_reviewed_bundle_mismatch'; END IF;
 SELECT count(*),COALESCE(sum(refund_minor),0) INTO n,total
 FROM financial_refund_component_applications WHERE
application_id=app.application_id;
 expected_n := jsonb_array_length(matched.bundle);
 IF n<>expected_n OR total<>app.amount_minor THEN
   RAISE EXCEPTION 'correction_partial_bundle';
 END IF;
 FOR component IN SELECT * FROM financial_refund_component_applications
   WHERE application_id=app.application_id ORDER BY allocation_key LOOP
   SELECT * INTO allocation FROM payment_item_allocations
     WHERE allocation_key=component.allocation_key FOR UPDATE;
   IF allocation.payment_id IS DISTINCT FROM app.payment_id
     OR allocation.order_id IS DISTINCT FROM app.order_id
     OR allocation.paid_item_id IS DISTINCT FROM component.paid_item_id
     OR allocation.payment_id IS DISTINCT FROM component.payment_id
     OR allocation.component<>'selection' OR allocation.currency<>'RUB'
     OR allocation.amount_minor IS DISTINCT FROM component.gross_minor
     OR NOT EXISTS (SELECT 1 FROM jsonb_array_elements(matched.bundle) b
       WHERE b->>'allocation_key'=component.allocation_key
       AND b->>'paid_item_id'=component.paid_item_id::text
       AND (b->>'gross_minor')::bigint=component.refund_minor)
   THEN RAISE EXCEPTION 'correction_component_source_mismatch'; END IF;
   IF EXISTS (SELECT 1 FROM item_assignments WHERE
paid_item_id=component.paid_item_id)
     OR EXISTS (SELECT 1 FROM paid_selection_accepted_deliveries WHERE
paid_item_id=component.paid_item_id)
     OR EXISTS (SELECT 1 FROM financial_obligations WHERE
paid_item_id=component.paid_item_id
       AND kind<>'client_referral')
     OR NOT EXISTS (SELECT 1 FROM order_items i JOIN order_intake_receipts r
       ON r.order_id=i.order_id JOIN orders o ON o.order_id=i.order_id
       WHERE i.paid_item_id=component.paid_item_id AND
r.client_id=o.advertiser_id
       AND app.recorded_at>i.selection_due_at
       AND r.result->>'selection_due_at'=i.quote_payload->>'selection_due_at'
       AND (r.result->>'selection_due_at')::timestamptz=i.selection_due_at
       AND r.result->>'terms_reference'=i.quote_payload->>'terms_reference')
   THEN RAISE EXCEPTION 'correction_unassigned_undelivered_due_required'; END
IF;
   SELECT COALESCE(sum(refund_minor),0) INTO prior
     FROM financial_refund_component_applications WHERE
allocation_key=component.allocation_key
       AND application_id<>app.application_id;
   IF prior<>component.prior_refund_minor OR
prior+component.refund_minor>allocation.amount_minor
   THEN RAISE EXCEPTION 'correction_component_capacity'; END IF;
   SELECT * INTO liability FROM financial_refund_liability_assessments
     WHERE component_application_id=component.component_application_id;
   IF NOT FOUND THEN RAISE EXCEPTION
'correction_liability_assessment_missing'; END IF;
   IF liability.business_key IS DISTINCT FROM
'client-selection:'||app.payment_id::text||':'||component.paid_item_id::text
   THEN RAISE EXCEPTION 'correction_original_basis_mismatch'; END IF;
   IF liability.status='covered_absence' THEN
     SELECT * INTO potential FROM financial_audit_events WHERE
id=liability.potential_id;
     IF potential.id IS NULL THEN RAISE EXCEPTION
'correction_covered_potential_missing'; END IF;
     IF capture.payload#>>'{attribution_history,status}' IS DISTINCT FROM
'assessed'
       OR capture.payload#>>'{attribution_history,fact,referrer_user_id}' IS
NOT NULL
       OR COALESCE(capture.payload#>>'{attribution_history,fact,reason}','')
          NOT IN ('unbound','revoked','self_referral','not_yet_effective')
       OR
NULLIF(capture.payload#>>'{attribution_history,fact,coverage_version}','') IS
NULL
       OR capture.payload#>>'{attribution_history,fact,covered_from}' IS NULL
       OR capture.payload#>>'{attribution_history,fact,observed_through}'
          IS NULL
       OR capture.payload#>>'{attribution_history,fact,referred_user_id}'
          IS DISTINCT FROM request.client_id::text
       OR
(capture.payload#>>'{attribution_history,fact,covered_from}')::timestamptz
           > (capture.payload->'capture'->>'captured_at')::timestamptz
       OR
(capture.payload#>>'{attribution_history,fact,observed_through}')::timestamptz
           < (capture.payload->'capture'->>'captured_at')::timestamptz THEN
       RAISE EXCEPTION 'correction_original_coverage_unavailable'; END IF;
     IF potential.action IS DISTINCT FROM 'potential_basis'
       OR potential.details->>'business_key' IS DISTINCT FROM
liability.business_key
       OR potential.details->>'kind' IS DISTINCT FROM 'client_referral'
       OR potential.details->>'paid_item_id' IS DISTINCT FROM
component.paid_item_id::text
       OR potential.details->>'payment_id' IS DISTINCT FROM app.payment_id::text
       OR potential.details->>'order_id' IS DISTINCT FROM app.order_id::text
       OR potential.details->>'currency' IS DISTINCT FROM 'RUB'
       OR (potential.details->>'base_minor')::bigint
          IS DISTINCT FROM component.gross_minor
       OR potential.details->>'referred_user_id'
          IS DISTINCT FROM request.client_id::text
       OR potential.details->>'event_id' IS DISTINCT FROM app.capture_id::text
       OR potential.details->>'recipient_id' IS NOT NULL
       OR capture.payload->>'client_referrer_id' IS NOT NULL
       OR liability.obligation_id IS NOT NULL OR liability.snapshot_id IS NOT
NULL
       OR liability.issuance_entry_id IS NOT NULL OR liability.movement_id IS
NOT NULL
       OR liability.frozen_rate_bps IS NOT NULL OR liability.override_id IS
NOT NULL
       OR liability.target_minor<>0 OR liability.already_cancelled_minor<>0 OR
liability.delta_minor<>0
       OR EXISTS (SELECT 1 FROM financial_obligations WHERE
business_key=liability.business_key)
     THEN RAISE EXCEPTION 'correction_covered_absence_unavailable'; END IF;
   ELSE
     SELECT * INTO original FROM financial_obligations WHERE
id=liability.obligation_id;
     SELECT * INTO snapshot FROM rate_snapshots WHERE id=original.snapshot_id;
     SELECT * INTO issuance FROM financial_movements WHERE
id=liability.issuance_entry_id;
     IF original.kind IS DISTINCT FROM 'client_referral'
       OR original.business_key IS DISTINCT FROM liability.business_key
       OR original.paid_item_id IS DISTINCT FROM component.paid_item_id
       OR original.order_id IS DISTINCT FROM app.order_id
       OR original.currency IS DISTINCT FROM 'RUB'
       OR original.base_minor IS DISTINCT FROM component.gross_minor
       OR snapshot.id IS DISTINCT FROM liability.snapshot_id
       OR snapshot.payment_id IS DISTINCT FROM app.payment_id
       OR snapshot.rate_bps IS DISTINCT FROM liability.frozen_rate_bps
       OR snapshot.override_id IS DISTINCT FROM liability.override_id
       OR issuance.obligation_id IS DISTINCT FROM original.id
       OR issuance.operation_key IS DISTINCT FROM
'issue:'||liability.business_key
       OR issuance.movement_type IS DISTINCT FROM 'issuance'
       OR issuance.amount_minor IS DISTINCT FROM original.amount_minor
       OR issuance.bucket_to IS DISTINCT FROM 'pending'
       OR liability.potential_id IS NOT NULL
     THEN RAISE EXCEPTION 'correction_original_issuance_mismatch'; END IF;
     -- a1 permits a full original component, whose exact target is its
     -- validated original gross commission. No new percentage formula.
     expected := original.amount_minor;
     SELECT COALESCE(sum(delta_minor),0) INTO prior FROM
financial_refund_liability_assessments
       WHERE obligation_id=original.id AND
assessment_id<>liability.assessment_id;
     IF liability.target_minor<>expected OR
liability.already_cancelled_minor<>prior
       OR liability.delta_minor<>expected-prior THEN
       RAISE EXCEPTION 'correction_cumulative_target_mismatch'; END IF;
     SELECT COALESCE(sum(CASE WHEN bucket_to='pending' THEN amount_minor ELSE
0 END
       - CASE WHEN bucket_from='pending' THEN amount_minor ELSE 0 END),0)
       INTO actual_pending FROM financial_movements WHERE
obligation_id=original.id;
     IF actual_pending<>original.amount_minor-liability.target_minor
       OR EXISTS (SELECT 1 FROM financial_movements WHERE
obligation_id=original.id
         AND (bucket_from IS NOT NULL AND bucket_from NOT IN
('pending','cancelled')
              OR bucket_to NOT IN ('pending','cancelled'))) THEN
       RAISE EXCEPTION 'correction_pending_only'; END IF;
     IF liability.delta_minor=0 THEN
       IF liability.movement_id IS NOT NULL THEN RAISE EXCEPTION
'correction_zero_journal'; END IF;
     ELSE
       SELECT * INTO movement FROM financial_movements WHERE
id=liability.movement_id;
       IF movement.obligation_id IS DISTINCT FROM original.id
         OR movement.source_entry_id IS DISTINCT FROM issuance.id
         OR movement.movement_type IS DISTINCT FROM 'reversal'
         OR movement.bucket_from IS DISTINCT FROM 'pending'
         OR movement.bucket_to IS DISTINCT FROM 'cancelled'
         OR movement.currency IS DISTINCT FROM 'RUB'
         OR movement.amount_minor IS DISTINCT FROM liability.delta_minor
         OR movement.case_id IS DISTINCT FROM app.case_id
         OR movement.refund_id IS DISTINCT FROM app.application_id
       THEN RAISE EXCEPTION 'correction_linked_cancellation_mismatch'; END IF;
     END IF;
     IF NOT EXISTS (
       SELECT 1 FROM financial_wallets w
       WHERE w.recipient_id=original.recipient_id AND w.currency='RUB'
       AND w.pending_minor=(
         SELECT COALESCE(sum(CASE WHEN m.bucket_to='pending'
           THEN m.amount_minor ELSE 0 END
           - CASE WHEN m.bucket_from='pending'
             THEN m.amount_minor ELSE 0 END),0)
         FROM financial_movements m JOIN financial_obligations o
           ON o.id=m.obligation_id
         WHERE o.recipient_id=original.recipient_id)
       AND w.cancelled_minor=(
         SELECT COALESCE(sum(CASE WHEN m.bucket_to='cancelled'
           THEN m.amount_minor ELSE 0 END
           - CASE WHEN m.bucket_from='cancelled'
             THEN m.amount_minor ELSE 0 END),0)
         FROM financial_movements m JOIN financial_obligations o
           ON o.id=m.obligation_id
         WHERE o.recipient_id=original.recipient_id)
     ) THEN RAISE EXCEPTION 'correction_projection_mismatch'; END IF;
   END IF;
 END LOOP;
 RETURN NEW;
END $$;
"""


def correction_trigger_sql(tables):
    statements = [GUARD_SQL]
    for key, table in tables.items():
        if key != "states":
            statements.append(
                "CREATE TRIGGER correction_fact_immutable BEFORE UPDATE "
                f"OR DELETE OR TRUNCATE ON {table.name} FOR EACH STATEMENT "
                "EXECUTE FUNCTION correction_deny_mutation();"
            )
        if key in ("applications", "components", "liabilities"):
            statements.append(
                "CREATE CONSTRAINT TRIGGER correction_application_guard "
                f"AFTER INSERT ON {table.name} DEFERRABLE INITIALLY DEFERRED "
                "FOR EACH ROW EXECUTE FUNCTION correction_check_application();"
            )
    return "\n".join(statements)
