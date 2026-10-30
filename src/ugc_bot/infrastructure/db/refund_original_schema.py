"""Preserve a reviewed source seal across proven delayed original assessment."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from ugc_bot.infrastructure.db.correction_approval_schema import APPROVAL_SQL


def refund_original_tables(metadata):
    def uid(name, target=None, **kwargs):
        return sa.Column(
            name,
            UUID(as_uuid=True),
            *(
                [sa.ForeignKey(target, deferrable=True, initially="DEFERRED")]
                if target
                else []
            ),
            nullable=False,
            **kwargs,
        )

    table = sa.Table(
        "financial_refund_original_assessments",
        metadata,
        uid("assessment_id", primary_key=True),
        uid("match_id", "financial_refund_matches.match_id", unique=True),
        uid(
            "command_id",
            "financial_correction_commands.command_id",
            unique=True,
        ),
        uid("case_id", "financial_correction_cases.case_id"),
        uid("capture_id", "outbox_events.event_id"),
        uid("payment_id", "payments.payment_id"),
        uid("order_id", "orders.order_id"),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column(
            "new_ground_ids",
            sa.JSON().with_variant(JSONB(), "postgresql"),
            nullable=False,
        ),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            (
                "jsonb_typeof(new_ground_ids)='array' AND "
                "jsonb_array_length(new_ground_ids) BETWEEN 1 AND 200"
            ),
            name="ck_refund_original_grounds",
        ).ddl_if(dialect="postgresql"),
    )
    return {"original_assessments": table}


ORIGINAL_VALIDATE_SQL = APPROVAL_SQL[
    APPROVAL_SQL.index(
        "CREATE OR REPLACE FUNCTION correction_validate_authority"
    ) : APPROVAL_SQL.index(
        "CREATE OR REPLACE FUNCTION correction_match_capsule"
    )
]


def refund_original_guards():
    selected = (
        "WHERE paid_item_id::text IN (SELECT\n "
        "jsonb_array_elements_text(request.paid_item_ids));"
    )
    all_grounds = (
        "FROM financial_obligations WHERE order_id=request.order_id),'[]'),"
    )
    if (
        ORIGINAL_VALIDATE_SQL.count(selected) != 2
        or ORIGINAL_VALIDATE_SQL.count(all_grounds) != 1
    ):
        raise RuntimeError("Refund approval source guard must be reviewed")
    patched = ORIGINAL_VALIDATE_SQL.replace(
        selected,
        selected[:-1]
        + (
            " AND\n"
            "correction_original_ground_visible(id,request.case_id,authority->>'source_hash');"
        ),
        1,
    ).replace(
        all_grounds,
        (
            "FROM financial_obligations WHERE order_id=request.order_id AND\n"
            "correction_original_ground_visible(id,request.case_id,authority->>'source_hash')),'[]'),"
        ),
    )
    return (
        ORIGINAL_GUARD_SQL
        + patched
        + """
CREATE TRIGGER refund_original_immutable BEFORE UPDATE OR DELETE OR TRUNCATE
ON financial_refund_original_assessments FOR EACH STATEMENT
EXECUTE FUNCTION financial_selection_deny_mutation();
CREATE CONSTRAINT TRIGGER refund_original_source_guard AFTER INSERT
ON financial_refund_original_assessments DEFERRABLE INITIALLY DEFERRED
FOR EACH ROW EXECUTE FUNCTION correction_check_original_assessment();
"""
    )


ORIGINAL_GUARD_SQL = """
CREATE OR REPLACE FUNCTION correction_original_ground_visible(ground_id uuid,
 selected_case uuid, selected_source text) RETURNS boolean LANGUAGE sql STABLE
AS $$
 SELECT NOT EXISTS(SELECT 1 FROM financial_refund_original_assessments a
 WHERE a.case_id=selected_case AND a.source_hash=selected_source
 AND a.new_ground_ids ? ground_id::text)
$$;
CREATE OR REPLACE FUNCTION correction_check_original_assessment() RETURNS
trigger
LANGUAGE plpgsql AS $$
DECLARE matched record; command record; app record; capture record; ground
record;
 snapshot record; issuance record; entry jsonb; n integer;
BEGIN
 SELECT * INTO matched FROM financial_refund_matches WHERE
match_id=NEW.match_id;
 SELECT * INTO command FROM financial_correction_commands WHERE
command_id=NEW.command_id;
 SELECT * INTO app FROM financial_refund_applications WHERE
match_id=NEW.match_id;
 SELECT * INTO capture FROM outbox_events WHERE event_id=NEW.capture_id;
 IF app.application_id IS NULL OR command.command_id IS NULL
 OR
(app.match_id,app.case_id,app.capture_id,app.payment_id,app.order_id,app.source_hash)
 IS DISTINCT FROM
(NEW.match_id,NEW.case_id,NEW.capture_id,NEW.payment_id,NEW.order_id,NEW.source_hash)
 OR
(matched.case_id,matched.capture_id,matched.payment_id,matched.order_id,matched.source_hash)
 IS DISTINCT FROM
(NEW.case_id,NEW.capture_id,NEW.payment_id,NEW.order_id,NEW.source_hash)
 OR command.action IS DISTINCT FROM 'ApplySelectionRefund'
 OR command.result->>'applied' IS DISTINCT FROM 'true'
 OR command.result->>'application_id' IS DISTINCT FROM
app.application_id::text
 OR capture.event_type IS DISTINCT FROM 'financial.client_snapshot_requested'
 OR capture.aggregate_id IS DISTINCT FROM NEW.order_id::text
 OR capture.payload->>'payment_id' IS DISTINCT FROM NEW.payment_id::text
 OR capture.payload->>'client_referrer_id' IS NULL
 OR NOT EXISTS(SELECT 1 FROM financial_client_assessments
 WHERE event_id=NEW.capture_id AND payment_id=NEW.payment_id AND
order_id=NEW.order_id)
 OR NOT EXISTS(SELECT 1 FROM users WHERE user_id=command.actor_id AND
admin=true AND status='active')
 THEN RAISE EXCEPTION 'correction_original_assessment_source_mismatch' USING
ERRCODE='23514'; END
IF;
 SELECT count(DISTINCT value) INTO n FROM
jsonb_array_elements_text(NEW.new_ground_ids);
 IF n<>jsonb_array_length(NEW.new_ground_ids) THEN
 RAISE EXCEPTION 'correction_original_assessment_duplicate' USING
ERRCODE='23514'; END IF;
 FOR entry IN SELECT value FROM jsonb_array_elements(NEW.new_ground_ids) LOOP
 SELECT * INTO ground FROM financial_obligations WHERE
id=(entry#>>'{}')::uuid;
 SELECT * INTO snapshot FROM rate_snapshots WHERE id=ground.snapshot_id;
 SELECT * INTO issuance FROM financial_movements WHERE
 operation_key='issue:'||ground.business_key;
 IF ground.kind IS DISTINCT FROM 'client_referral'
 OR ground.order_id IS DISTINCT FROM NEW.order_id OR ground.currency IS
DISTINCT FROM 'RUB'
 OR ground.business_key IS DISTINCT FROM
'client-selection:'||NEW.payment_id::text||':'||ground.paid_item_id::text
 OR ground.recipient_id::text IS DISTINCT FROM
capture.payload->>'client_referrer_id'
 OR ground.base_minor IS DISTINCT FROM (SELECT selection_minor FROM
order_items WHERE paid_item_id=ground.paid_item_id)
 OR snapshot.payment_id IS DISTINCT FROM NEW.payment_id
 OR snapshot.referred_user_id::text IS DISTINCT FROM
capture.payload#>>'{capture,client_id}'
 OR snapshot.effective_at IS DISTINCT FROM
(capture.payload#>>'{capture,captured_at}')::timestamptz
 OR ground.amount_minor IS DISTINCT FROM
floor((ground.base_minor::numeric*snapshot.rate_bps+5000)/10000)::bigint
 OR issuance.obligation_id IS DISTINCT FROM ground.id
 OR issuance.event_id IS DISTINCT FROM NEW.capture_id::text
 OR issuance.actor_kind IS DISTINCT FROM 'user'
 OR issuance.actor_id::text IS DISTINCT FROM
capture.payload#>>'{capture,client_id}'
 OR issuance.movement_type IS DISTINCT FROM 'issuance' OR issuance.bucket_to
IS DISTINCT FROM 'pending'
 OR issuance.recorded_at IS DISTINCT FROM NEW.recorded_at
 OR issuance.recorded_at<matched.recorded_at
 THEN RAISE EXCEPTION 'correction_original_assessment_ground_mismatch' USING
ERRCODE='23514'; END
IF;
 END LOOP;
 RETURN NEW;
END $$;
"""
