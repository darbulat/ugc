"""Immutable reserve requests, reviews, allocations and contact disclosures."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

JSON = sa.JSON().with_variant(JSONB(), "postgresql")


def reference(name, target, *, unique=False):
    return sa.Column(
        name,
        UUID(as_uuid=True),
        sa.ForeignKey(target),
        nullable=False,
        unique=unique,
    )


def replacement_tables(metadata):
    if "paid_replacement_requests" in metadata.tables:
        return {
            key: metadata.tables["paid_replacement_" + key]
            for key in (
                "requests",
                "decisions",
                "allocations",
                "contacts",
                "commands",
            )
        }
    requests = sa.Table(
        "paid_replacement_requests",
        metadata,
        sa.Column("request_id", UUID(as_uuid=True), primary_key=True),
        reference("paid_item_id", "order_items.paid_item_id"),
        reference("order_id", "orders.order_id"),
        reference("client_id", "users.user_id"),
        reference("payment_id", "payments.payment_id"),
        reference("old_assignment_id", "item_assignments.assignment_id"),
        sa.Column("old_assignment_version", sa.Integer, nullable=False),
        reference(
            "candidate_interest_id", "paid_selection_interests.interest_id"
        ),
        reference("actor_id", "users.user_id"),
        sa.Column("reason_code", sa.String(30), nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("evidence_reference", sa.Text, nullable=False),
        sa.Column("original_paid_pool", sa.Integer, nullable=False),
        sa.Column("capture_hash", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "version=1 AND old_assignment_version>=1 AND original_paid_pool>0",
            name="ck_replacement_request_version",
        ),
        sa.CheckConstraint(
            "reason_code IN ('refusal','lost_contact','brief_mismatch') "
            "AND length(trim(reason)) BETWEEN 1 AND 4000 "
            "AND length(trim(evidence_reference)) BETWEEN 1 AND 4000",
            name="ck_replacement_request_evidence",
        ),
        sa.Index("ix_replacement_request_order", "order_id", "requested_at"),
    )
    decisions = sa.Table(
        "paid_replacement_decisions",
        metadata,
        sa.Column("replacement_id", UUID(as_uuid=True), primary_key=True),
        reference(
            "request_id", "paid_replacement_requests.request_id", unique=True
        ),
        reference("paid_item_id", "order_items.paid_item_id"),
        reference("order_id", "orders.order_id"),
        reference("actor_id", "users.user_id"),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("action", sa.String(20), nullable=False),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("evidence_reference", sa.Text, nullable=False),
        sa.Column("exception_reason", sa.Text),
        sa.Column("exception_evidence", sa.Text),
        sa.Column("original_paid_pool", sa.Integer, nullable=False),
        sa.Column("prior_replacements", sa.Integer, nullable=False),
        sa.Column("reserve_limit", sa.Integer, nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "version=2 AND action IN ('approve','reject') "
            "AND original_paid_pool>0 AND prior_replacements>=0 "
            "AND reserve_limit=original_paid_pool/5",
            name="ck_replacement_decision_version",
        ),
        sa.CheckConstraint(
            "length(trim(reason)) BETWEEN 1 AND 4000 "
            "AND length(trim(evidence_reference)) BETWEEN 1 AND 4000",
            name="ck_replacement_decision_evidence",
        ),
        sa.CheckConstraint(
            "(exception_reason IS NULL AND exception_evidence IS NULL) "
            "OR (exception_reason IS NOT NULL "
            "AND exception_evidence IS NOT NULL "
            "AND length(trim(exception_reason)) BETWEEN 1 AND 4000 "
            "AND length(trim(exception_evidence)) BETWEEN 1 AND 4000)",
            name="ck_replacement_exception_evidence",
        ),
        sa.CheckConstraint(
            "action='reject' OR prior_replacements<reserve_limit "
            "OR (exception_reason IS NOT NULL "
            "AND exception_evidence IS NOT NULL)",
            name="ck_replacement_reserve_review",
        ),
    )
    allocations = sa.Table(
        "paid_replacement_allocations",
        metadata,
        reference(
            "replacement_id",
            "paid_replacement_decisions.replacement_id",
            unique=True,
        ),
        reference("paid_item_id", "order_items.paid_item_id"),
        reference(
            "old_assignment_id", "item_assignments.assignment_id", unique=True
        ),
        reference(
            "assignment_id", "item_assignments.assignment_id", unique=True
        ),
        sa.Column("assignment_version", sa.Integer, nullable=False),
        reference(
            "candidate_interest_id",
            "paid_selection_interests.interest_id",
            unique=True,
        ),
        sa.Column(
            "manager_id", UUID(as_uuid=True), sa.ForeignKey("users.user_id")
        ),
        sa.Column("movement_ids", JSON, nullable=False),
        sa.Column("allocated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("replacement_id"),
        sa.CheckConstraint(
            "old_assignment_id<>assignment_id AND assignment_version>1",
            name="ck_replacement_new_assignment",
        ),
    )
    contacts = sa.Table(
        "paid_replacement_contacts",
        metadata,
        sa.Column("contact_id", UUID(as_uuid=True), primary_key=True),
        reference(
            "replacement_id", "paid_replacement_allocations.replacement_id"
        ),
        reference("actor_id", "users.user_id"),
        sa.Column("reason", sa.Text, nullable=False),
        sa.Column("evidence_reference", sa.Text, nullable=False),
        sa.Column("contact", JSON, nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(trim(reason)) BETWEEN 1 AND 4000 "
            "AND length(trim(evidence_reference)) BETWEEN 1 AND 4000",
            name="ck_replacement_contact_reason",
        ),
    )
    commands = sa.Table(
        "paid_replacement_commands",
        metadata,
        reference("actor_id", "users.user_id"),
        sa.Column("operation_key", sa.String(256), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("result", JSON, nullable=False),
        sa.PrimaryKeyConstraint("actor_id", "operation_key"),
    )
    result = dict(
        requests=requests,
        decisions=decisions,
        allocations=allocations,
        contacts=contacts,
        commands=commands,
    )
    for table in result.values():
        sa.event.listen(
            table,
            "after_create",
            sa.DDL(immutability_sql((table,))).execute_if(dialect="postgresql"),
        )
    sa.event.listen(
        allocations,
        "after_create",
        sa.DDL(authority_sql()).execute_if(dialect="postgresql"),
    )
    return result


def immutability_sql(tables):
    return """
CREATE OR REPLACE FUNCTION paid_replacement_deny_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
 RAISE EXCEPTION 'paid_replacement_history_immutable' USING ERRCODE='23514';
END $$;
""" + "\n".join(
        "CREATE TRIGGER paid_replacement_immutable "
        f"BEFORE UPDATE OR DELETE OR TRUNCATE ON {table.name} "
        "FOR EACH STATEMENT "
        "EXECUTE FUNCTION paid_replacement_deny_mutation();"
        for table in tables
    )


def migration_metadata():
    metadata = sa.MetaData()
    for name, key in (
        ("users", "user_id"),
        ("orders", "order_id"),
        ("order_items", "paid_item_id"),
        ("payments", "payment_id"),
        ("item_assignments", "assignment_id"),
        ("paid_selection_interests", "interest_id"),
    ):
        sa.Table(name, metadata, sa.Column(key, UUID, primary_key=True))
    return metadata


def review_guard_sql(*, automatic=False):
    sql = """
CREATE OR REPLACE FUNCTION paid_replacement_review_guard() RETURNS trigger
LANGUAGE plpgsql AS $$ DECLARE request paid_replacement_requests; total integer;
BEGIN
 SELECT * INTO request FROM paid_replacement_requests
 WHERE request_id=NEW.request_id;
 IF NOT FOUND OR request.paid_item_id<>NEW.paid_item_id
  OR request.order_id<>NEW.order_id
  OR request.original_paid_pool<>NEW.original_paid_pool
  OR NEW.reviewed_at<request.requested_at
  OR NOT EXISTS(SELECT 1 FROM users WHERE user_id=NEW.actor_id
                AND admin AND status='active') THEN
  RAISE EXCEPTION 'replacement_review_source_invalid' USING ERRCODE='23514';
 END IF;
 SELECT count(*) INTO total FROM payment_item_allocations
 WHERE payment_id=request.payment_id AND component='selection'
  AND order_id=request.order_id AND currency='RUB'
  AND amount_minor=(SELECT i.selection_minor FROM order_items i WHERE
i.paid_item_id=payment_item_allocations.paid_item_id);
 IF total<>NEW.original_paid_pool THEN
  RAISE EXCEPTION 'replacement_original_pool_invalid' USING ERRCODE='23514';
 END IF;
 IF NEW.action='approve' AND (
   NOT EXISTS(SELECT 1 FROM item_assignments
     WHERE assignment_id=request.old_assignment_id
      AND paid_item_id=request.paid_item_id
      AND version=request.old_assignment_version AND valid_to IS NULL)
   OR EXISTS(SELECT 1 FROM financial_collaboration_events e
     JOIN item_assignments a ON a.assignment_id=e.assignment_id
     WHERE a.paid_item_id=request.paid_item_id
      AND e.result_payload->'collaboration'->>'success_final_at' IS NOT NULL)
 ) THEN
  RAISE EXCEPTION 'replacement_completed_or_obsolete' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
"""
    if not automatic:
        return sql
    manual_guard = (
        "OR NOT EXISTS(SELECT 1 FROM users WHERE user_id=NEW.actor_id\n"
        "                AND admin AND status='active')"
    )
    sql = sql.replace(
        "total integer;",
        "total integer; automatic_review boolean;",
    ).replace(
        " IF NOT FOUND OR request.paid_item_id",
        """ automatic_review := EXISTS(
 SELECT 1 FROM telegram_order_exceptions
 WHERE automatic_request_id=NEW.request_id);
 IF request.request_id IS NULL OR request.paid_item_id""",
    )
    return sql.replace(
        manual_guard,
        """
  OR (NOT automatic_review AND NOT EXISTS(
      SELECT 1 FROM users WHERE user_id=NEW.actor_id
        AND admin AND status='active'))
  OR (automatic_review AND (
      NEW.action<>'approve' OR NEW.exception_reason IS NOT NULL
      OR NEW.prior_replacements>=NEW.reserve_limit
      OR request.reason_code<>'lost_contact'
      OR NOT EXISTS (
        SELECT 1 FROM telegram_order_exceptions e
        JOIN telegram_order_summary_jobs j ON j.report_id=e.report_id
        JOIN orders o ON o.order_id=e.order_id
        JOIN item_assignments original ON original.assignment_id=e.assignment_id
        JOIN users client ON client.user_id=e.client_id
        WHERE e.automatic_request_id=NEW.request_id
          AND e.order_id=NEW.order_id AND e.paid_item_id=NEW.paid_item_id
          AND e.assignment_id=request.old_assignment_id
          AND e.client_id=request.client_id AND e.client_id=NEW.actor_id
          AND o.advertiser_id=e.client_id AND o.status='active'
          AND client.status='active'
          AND original.creator_id=e.creator_id
          AND j.order_id=e.order_id AND j.recipient_id=e.creator_id
          AND e.reason='no_answer' AND e.state='waiting'
          AND e.answer_due_at=j.delivered_at+interval '24 hours'
          AND e.answer_due_at<=NEW.reviewed_at
          AND j.kind='creator' AND j.state='sent'
          AND j.provider_reference IS NOT NULL
      )
      OR NEW.prior_replacements <> (
          SELECT count(*) FROM paid_replacement_allocations a
          JOIN paid_replacement_decisions d USING (replacement_id)
          WHERE d.order_id=NEW.order_id
      )
  ))""",
    )


def authority_sql(*, automatic=False):
    return (
        review_guard_sql(automatic=automatic)
        + """
CREATE TRIGGER paid_replacement_review_source BEFORE INSERT
 ON paid_replacement_decisions FOR EACH ROW
 EXECUTE FUNCTION paid_replacement_review_guard();
CREATE OR REPLACE FUNCTION paid_replacement_allocation_guard() RETURNS trigger
LANGUAGE plpgsql AS $$ DECLARE proof record; movement text;
BEGIN
 SELECT d.action, d.actor_id, d.reviewed_at, r.paid_item_id,
  r.old_assignment_id, r.old_assignment_version, r.candidate_interest_id,
  prior_assignment.valid_to AS old_ended, fresh.paid_item_id AS new_item,
  fresh.version AS new_version, fresh.valid_from AS new_started,
  fresh.creator_id AS new_creator, fresh.actor_id AS assigned_by,
  fresh.manager_id AS assigned_manager, i.creator_id AS interested_creator,
  i.accepted AS initially_accepted
 INTO proof FROM paid_replacement_decisions d
 JOIN paid_replacement_requests r ON r.request_id=d.request_id
 JOIN item_assignments prior_assignment
  ON prior_assignment.assignment_id=r.old_assignment_id
 JOIN item_assignments fresh ON fresh.assignment_id=NEW.assignment_id
 JOIN paid_selection_interests i ON i.interest_id=r.candidate_interest_id
 WHERE d.replacement_id=NEW.replacement_id;
 IF NOT FOUND OR proof.action<>'approve'
  OR proof.paid_item_id<>NEW.paid_item_id
  OR proof.new_item<>NEW.paid_item_id
  OR proof.old_assignment_id<>NEW.old_assignment_id
  OR proof.candidate_interest_id<>NEW.candidate_interest_id
  OR proof.new_version<>NEW.assignment_version
  OR proof.new_version<>proof.old_assignment_version+1
  OR proof.old_ended IS DISTINCT FROM NEW.allocated_at
  OR proof.new_started<>NEW.allocated_at
  OR proof.reviewed_at<>NEW.allocated_at
  OR proof.new_creator<>proof.interested_creator
  OR proof.assigned_by<>proof.actor_id
  OR proof.assigned_manager IS DISTINCT FROM NEW.manager_id
  OR proof.initially_accepted THEN
  RAISE EXCEPTION 'replacement_allocation_source_invalid'
   USING ERRCODE='23514';
 END IF;
 FOR movement IN SELECT jsonb_array_elements_text(NEW.movement_ids::jsonb)
 LOOP
  IF NOT EXISTS(SELECT 1 FROM financial_movements m
    JOIN financial_obligations o ON o.id=m.obligation_id
    WHERE m.id=movement::uuid AND m.case_id=NEW.replacement_id
     AND m.refund_id=NEW.replacement_id AND m.movement_type='reversal'
     AND m.bucket_to='cancelled' AND o.paid_item_id=NEW.paid_item_id
     AND o.kind IN ('creator_referral','management')) THEN
   RAISE EXCEPTION 'replacement_cancellation_source_invalid'
    USING ERRCODE='23514';
  END IF;
 END LOOP;
 RETURN NEW;
END $$;
CREATE TRIGGER paid_replacement_allocation_source BEFORE INSERT
 ON paid_replacement_allocations FOR EACH ROW
 EXECUTE FUNCTION paid_replacement_allocation_guard();
"""
    )
