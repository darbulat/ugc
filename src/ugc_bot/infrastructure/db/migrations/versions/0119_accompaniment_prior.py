"""Account for every permanent cancellation before applying a real refund."""

import sqlalchemy as sa
from alembic import op

from ugc_bot.infrastructure.db.accompaniment_refund_schema import (
    APPLICATION_GUARD,
)

revision = "0119_accompaniment_prior"
down_revision = "0118_financial_review_restore"
branch_labels = None
depends_on = None

# Frozen pre-fix function; downgrade never derives history from a newer helper.
LEGACY_APPLICATION_GUARD = """
CREATE OR REPLACE FUNCTION accompaniment_refund_check_application() RETURNS
trigger
LANGUAGE plpgsql AS $$
DECLARE observation record; item record; payment record; work record; policy
record;
 manager record; proof record; prior_customer bigint; prior_manager bigint;
 expected_customer bigint; expected_manager bigint; actual bigint; stage_bps
integer;
BEGIN
 SELECT * INTO observation FROM financial_accompaniment_refund_observations
 WHERE observation_id=NEW.observation_id;
 SELECT * INTO item FROM order_items WHERE paid_item_id=NEW.paid_item_id;
 SELECT * INTO payment FROM payments WHERE payment_id=NEW.payment_id;
 SELECT * INTO work FROM financial_collaborations WHERE
assignment_id=NEW.assignment_id;
 SELECT * INTO policy FROM financial_policy_versions WHERE
version=NEW.policy_version;
 IF observation.observation_id IS NULL OR item.accompaniment_minor<>120000
 OR observation.paid_item_id IS DISTINCT FROM item.paid_item_id
 OR observation.payment_id IS DISTINCT FROM payment.payment_id
 OR payment.order_id IS DISTINCT FROM item.order_id
 OR observation.original_payment_reference IS DISTINCT FROM
payment.external_id
 OR observation.currency IS DISTINCT FROM 'RUB'
 OR observation.amount_minor IS DISTINCT FROM NEW.customer_delta_minor
 OR observation.proof_claimed IS DISTINCT FROM true
 OR observation.occurred_at<item.captured_at
 OR observation.occurred_at>NEW.recorded_at
 OR NEW.policy_version IS DISTINCT FROM item.policy_version
 OR NEW.rules IS DISTINCT FROM policy.rules->'refund_rules'
 OR length(trim(NEW.reason))=0 OR length(trim(NEW.evidence_reference))=0
 OR NEW.evidence_hash !~ '^[0-9a-f]{64}$'
 OR NOT EXISTS(SELECT 1 FROM users WHERE user_id=NEW.actor_id AND admin=true
AND status='active')
 THEN RAISE EXCEPTION 'accompaniment_refund_source_mismatch' USING
ERRCODE='23514'; END IF;
 IF NEW.work_version=0 THEN
  IF NEW.assignment_id IS NOT NULL OR NEW.stage IS NOT NULL
  OR NEW.manager_target_minor<>0 OR EXISTS(
   SELECT 1 FROM financial_collaborations c JOIN item_assignments a
   ON a.assignment_id=c.assignment_id WHERE a.paid_item_id=NEW.paid_item_id
   AND a.valid_to IS NULL) THEN
   RAISE EXCEPTION 'accompaniment_absence_source_changed'
   USING ERRCODE='23514'; END IF;
 ELSE
  IF work.assignment_id IS NULL OR NEW.recorded_at<work.updated_at
  OR work.paid_item_id IS DISTINCT FROM item.paid_item_id
  OR work.version IS DISTINCT FROM NEW.work_version
  OR work.state IS DISTINCT FROM NEW.stage
  OR work.policy_version IS DISTINCT FROM NEW.policy_version
  OR NOT EXISTS(SELECT 1 FROM item_assignments a
   WHERE a.assignment_id=NEW.assignment_id AND a.valid_to IS NULL)
  THEN RAISE EXCEPTION 'accompaniment_refund_source_mismatch'
   USING ERRCODE='23514'; END IF;
 END IF;
 SELECT * INTO proof FROM financial_physical_proof_claims
 WHERE observation_id=observation.observation_id AND
command_id=observation.command_id
 AND producer='refund' AND intent_id=observation.observation_id AND
direction='outgoing'
 AND reference=trim(observation.bank_reference);
 IF NOT FOUND THEN RAISE EXCEPTION 'accompaniment_refund_proof_missing'
USING ERRCODE='23514'; END
IF;
 SELECT
COALESCE(sum(customer_delta_minor),0),COALESCE(sum(manager_delta_minor),0)
 INTO prior_customer,prior_manager FROM
financial_accompaniment_refund_applications
 WHERE paid_item_id=NEW.paid_item_id AND application_id<>NEW.application_id;
 IF NEW.customer_delta_minor<>NEW.customer_target_minor-prior_customer
 OR NEW.manager_delta_minor<>NEW.manager_target_minor-prior_manager
 THEN RAISE EXCEPTION 'accompaniment_refund_cumulative_mismatch' USING
ERRCODE='23514'; END IF;
 IF NEW.stage<>'disputed' AND NEW.rules->'accompaniment_refund_rates_bps' ?
NEW.stage THEN
   stage_bps :=
(NEW.rules->'accompaniment_refund_rates_bps'->>NEW.stage)::integer;
   expected_customer := (120000::bigint*stage_bps+5000)/10000;
   IF NEW.customer_target_minor<>expected_customer THEN
    RAISE EXCEPTION 'accompaniment_refund_policy_mismatch' USING
ERRCODE='23514'; END IF;
 END IF;
 SELECT o.* INTO manager FROM financial_obligations o JOIN rate_snapshots s ON
s.id=o.snapshot_id
 WHERE o.paid_item_id=NEW.paid_item_id AND o.kind='management'
 AND s.payment_id=NEW.payment_id;
 IF NOT FOUND THEN expected_manager:=0;
 ELSIF NEW.rules->>'accompaniment_manager_refund_mode'='retain_earned' THEN
expected_manager:=0;
 ELSIF NEW.rules->>'accompaniment_manager_refund_mode'='proportional' THEN
  expected_manager:=(60000::bigint*NEW.customer_target_minor+60000)/120000;
 ELSE expected_manager:=NEW.manager_target_minor; END IF;
 IF NEW.manager_target_minor<>expected_manager THEN
  RAISE EXCEPTION 'accompaniment_manager_policy_mismatch' USING
ERRCODE='23514'; END IF;
 SELECT COALESCE(sum(m.amount_minor),0) INTO actual FROM financial_movements m
 WHERE m.refund_id=NEW.application_id AND m.case_id=NEW.application_id
 AND m.obligation_id=manager.id AND m.movement_type IN ('reversal','debt');
 IF actual<>NEW.manager_delta_minor OR EXISTS(
 SELECT 1 FROM financial_movements m WHERE m.refund_id=NEW.application_id
 AND (m.obligation_id IS DISTINCT FROM manager.id OR m.movement_type NOT IN
('reversal','debt')
 OR m.actor_kind<>'admin' OR m.actor_id IS DISTINCT FROM NEW.actor_id))
 THEN RAISE EXCEPTION 'accompaniment_manager_journal_mismatch' USING
ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
"""


def upgrade():
    op.get_bind().exec_driver_sql(APPLICATION_GUARD)


def downgrade():
    db = op.get_bind()
    db.exec_driver_sql(
        "LOCK TABLE financial_accompaniment_refund_applications "
        "IN ACCESS EXCLUSIVE MODE"
    )
    if db.scalar(
        sa.text(
            "SELECT 1 FROM financial_accompaniment_refund_applications LIMIT 1"
        )
    ):
        raise RuntimeError("accompaniment_refund_history_exists")
    db.exec_driver_sql(LEGACY_APPLICATION_GUARD)
