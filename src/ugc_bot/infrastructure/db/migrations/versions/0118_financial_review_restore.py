"""Restore only case-owned blocks actually consumed by cancellation."""

import sqlalchemy as sa
from alembic import op

from ugc_bot.infrastructure.db.financial_review_schema import RESTORATION_SQL

revision = "0118_financial_review_restore"
down_revision = "0117_financial_reviews"
branch_labels = None
depends_on = None


# Frozen 0117 definitions: empty downgrade never reads newer guard helpers.
LEGACY_RESTORATION_SQL = """
CREATE OR REPLACE FUNCTION financial_review_before_resolution() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE c record; o record; prior bigint; maturity timestamptz;
BEGIN
 SELECT * INTO c FROM financial_review_cases WHERE case_id=NEW.case_id;
 SELECT * INTO o FROM financial_obligations WHERE id=c.obligation_id;
 IF c.case_id IS NULL OR NEW.expected_source_hash IS DISTINCT FROM
 correction_approval_hash(financial_review_document(c.obligation_id))
 OR NOT EXISTS(SELECT 1 FROM users WHERE user_id=NEW.actor_id
 AND admin=true AND status='active')
 OR length(trim(NEW.reason))=0 OR length(trim(NEW.evidence_reference))=0
 OR NEW.evidence_hash !~ '^[0-9a-f]{64}$' OR NEW.resolved_at<c.opened_at
 OR EXISTS(SELECT 1 FROM financial_movements WHERE obligation_id=o.id
 AND recorded_at>NEW.resolved_at) THEN
 RAISE EXCEPTION 'financial_review_resolution_source_changed'
 USING ERRCODE='23514'; END IF;
 SELECT COALESCE(sum(amount_minor),0) INTO prior FROM financial_movements
 WHERE obligation_id=o.id AND movement_type IN ('reversal','debt');
 IF NEW.prior_cancelled_minor<>prior OR NEW.target_minor>o.amount_minor
 OR (NEW.decision='no_adjustment' AND NEW.target_minor<>prior)
 OR (NEW.decision='cumulative_cancel' AND (SELECT COALESCE(sum(
 CASE WHEN bucket_to='reserved' THEN amount_minor ELSE 0 END-
 CASE WHEN bucket_from='reserved' THEN amount_minor ELSE 0 END),0)
 FROM financial_movements WHERE obligation_id=o.id)>0) THEN
 RAISE EXCEPTION 'financial_review_cancellation_mismatch'
 USING ERRCODE='23514'; END IF;
 IF o.kind='manual_adjustment' THEN
  SELECT release_at INTO maturity FROM financial_manual_grants
  WHERE 'manual-grant:'||grant_id::text=o.business_key;
 ELSIF o.kind='client_referral' THEN
  SELECT release_at INTO maturity FROM financial_selection_schedules
  WHERE paid_item_id=o.paid_item_id;
 END IF;
 IF maturity IS NULL THEN
  SELECT release_at INTO maturity FROM financial_obligation_maturity
  WHERE obligation_id=o.id;
 END IF;
 IF maturity IS NULL THEN maturity:=o.available_at; END IF;
 IF NEW.release_at IS DISTINCT FROM maturity
 OR NEW.restored_buckets IS DISTINCT FROM financial_review_restores(
 c.blocked_buckets,NEW.target_minor-c.prior_cancelled_minor,maturity,
 NEW.resolved_at) THEN
 RAISE EXCEPTION 'financial_review_restore_maturity_mismatch'
 USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE OR REPLACE FUNCTION financial_review_check_application() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE c record; r record; command record; bucket text; amount bigint;
 actual bigint; row_count integer; prior_debt bigint;
BEGIN
 IF TG_TABLE_NAME='financial_review_cases' THEN c:=NEW;
 ELSE SELECT * INTO c FROM financial_review_cases WHERE case_id=NEW.case_id;
 END IF;
 SELECT * INTO command FROM financial_review_commands WHERE
 actor_id=c.opened_by AND operation_key=c.operation_key;
 IF command.actor_id IS NULL OR command.result->>'case_id'
 IS DISTINCT FROM c.case_id::text
 OR command.result->>'state' IS DISTINCT FROM 'open'
 OR (command.result->>'version')::int IS DISTINCT FROM 1 THEN
 RAISE EXCEPTION 'financial_review_open_receipt_missing'
 USING ERRCODE='23514'; END IF;
 FOREACH bucket IN ARRAY ARRAY['pending','hold','available'] LOOP
  SELECT count(*),COALESCE(sum(amount_minor),0) INTO row_count,actual
  FROM financial_movements WHERE operation_key=
  'financial-review:'||c.case_id::text||':block:'||bucket
  AND (obligation_id,case_id,currency,actor_id,actor_kind,movement_type,
  bucket_from,bucket_to,effective_at,recorded_at,event_id)
  IS NOT DISTINCT FROM (c.obligation_id,c.case_id,c.currency,c.opened_by,
  'admin'::text,'transfer'::text,bucket,'blocked'::text,c.opened_at,c.opened_at,
  c.case_id::text);
  amount := (c.blocked_buckets->>bucket)::bigint;
  IF actual<>amount OR row_count<>(CASE WHEN amount>0 THEN 1 ELSE 0 END) THEN
   RAISE EXCEPTION 'financial_review_block_application_mismatch'
   USING ERRCODE='23514'; END IF;
 END LOOP;
 IF TG_TABLE_NAME='financial_review_cases' THEN RETURN NULL; END IF;
 r:=NEW;
 SELECT * INTO command FROM financial_review_commands WHERE
 actor_id=r.actor_id AND operation_key=r.operation_key;
 IF command.actor_id IS NULL OR command.result->>'case_id'
 IS DISTINCT FROM c.case_id::text
 OR command.result->>'state' IS DISTINCT FROM 'resolved'
 OR (command.result->>'version')::int IS DISTINCT FROM 2
 OR command.result->>'decision' IS DISTINCT FROM r.decision
 OR (command.result->>'target_minor')::bigint IS DISTINCT FROM r.target_minor
 OR (command.result->>'cancelled_delta_minor')::bigint
 IS DISTINCT FROM r.cancelled_delta_minor
 OR (command.result->>'debt_created_minor')::bigint
 IS DISTINCT FROM r.debt_created_minor THEN
 RAISE EXCEPTION 'financial_review_resolution_receipt_missing'
 USING ERRCODE='23514'; END IF;
 SELECT COALESCE(sum(amount_minor),0) INTO actual FROM financial_movements
 WHERE case_id=c.case_id AND refund_id=c.case_id
 AND obligation_id=c.obligation_id AND movement_type IN ('reversal','debt');
 IF actual<>r.cancelled_delta_minor THEN
 RAISE EXCEPTION 'financial_review_cancel_application_mismatch'
 USING ERRCODE='23514'; END IF;
 SELECT COALESCE(sum(amount_minor),0) INTO actual FROM financial_movements
 WHERE case_id=c.case_id AND refund_id=c.case_id
 AND obligation_id=c.obligation_id AND movement_type='debt';
 IF actual<>r.debt_created_minor OR EXISTS(SELECT 1 FROM financial_movements
 WHERE refund_id=c.case_id AND (obligation_id<>c.obligation_id
 OR actor_id IS DISTINCT FROM r.actor_id OR actor_kind<>'admin'
 OR recorded_at<>r.resolved_at OR effective_at<>r.resolved_at
 OR movement_type NOT IN ('reversal','debt'))) THEN
 RAISE EXCEPTION 'financial_review_debt_application_mismatch'
 USING ERRCODE='23514'; END IF;
 FOREACH bucket IN ARRAY ARRAY['pending','hold','available'] LOOP
  SELECT count(*),COALESCE(sum(amount_minor),0) INTO row_count,actual
  FROM financial_movements WHERE operation_key=
  'financial-review:'||c.case_id::text||':restore:'||bucket
  AND (obligation_id,case_id,currency,actor_id,actor_kind,movement_type,
  bucket_from,bucket_to,effective_at,recorded_at,event_id)
  IS NOT DISTINCT FROM (c.obligation_id,c.case_id,c.currency,r.actor_id,
  'admin'::text,'transfer'::text,'blocked'::text,bucket,r.resolved_at,
  r.resolved_at,c.case_id::text);
  amount := (r.restored_buckets->>bucket)::bigint;
  IF actual<>amount OR row_count<>(CASE WHEN amount>0 THEN 1 ELSE 0 END) THEN
   RAISE EXCEPTION 'financial_review_restore_application_mismatch'
   USING ERRCODE='23514'; END IF;
 END LOOP;
 RETURN NULL;
END $$;
"""


def upgrade():
    connection = op.get_bind()
    connection.exec_driver_sql(
        "LOCK TABLE financial_review_cases,financial_review_resolutions "
        "IN SHARE ROW EXCLUSIVE MODE"
    )
    connection.exec_driver_sql(RESTORATION_SQL)


def downgrade():
    connection = op.get_bind()
    connection.exec_driver_sql(
        "LOCK TABLE financial_review_cases,financial_review_resolutions "
        "IN ACCESS EXCLUSIVE MODE"
    )
    if connection.scalar(
        sa.text(
            "SELECT 1 FROM financial_review_cases UNION ALL "
            "SELECT 1 FROM financial_review_resolutions LIMIT 1"
        )
    ):
        raise RuntimeError("financial_review_history_exists")
    connection.exec_driver_sql(LEGACY_RESTORATION_SQL)
    connection.exec_driver_sql(
        "DROP FUNCTION financial_review_blocked_cancelled(uuid,jsonb)"
    )
