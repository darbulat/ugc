"""Immutable real accompaniment refund reports and reviewed applications."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


def accompaniment_refund_tables(metadata):
    json = sa.JSON().with_variant(JSONB(), "postgresql")

    def uid(name, target=None, **kwargs):
        return sa.Column(
            name,
            UUID(as_uuid=True),
            *([sa.ForeignKey(target)] if target else []),
            **kwargs,
        )

    def text(name):
        return sa.Column(name, sa.Text, nullable=False)

    def at(name):
        return sa.Column(name, sa.DateTime(timezone=True), nullable=False)

    commands = sa.Table(
        "financial_accompaniment_refund_commands",
        metadata,
        uid("actor_id", "users.user_id", nullable=False),
        text("operation_key"),
        text("payload_hash"),
        sa.Column("result", json, nullable=False),
        at("recorded_at"),
        sa.PrimaryKeyConstraint("actor_id", "operation_key"),
    )
    observations = sa.Table(
        "financial_accompaniment_refund_observations",
        metadata,
        uid("observation_id", primary_key=True),
        uid("command_id", nullable=False),
        uid("actor_id", "users.user_id", nullable=False),
        text("operation_key"),
        uid("paid_item_id", "order_items.paid_item_id", nullable=False),
        uid("payment_id", "payments.payment_id", nullable=False),
        text("original_payment_reference"),
        sa.Column("amount_minor", sa.BigInteger, nullable=False),
        text("currency"),
        text("bank_account_label"),
        text("bank_reference"),
        at("occurred_at"),
        text("reason"),
        text("evidence_reference"),
        text("evidence_hash"),
        sa.Column("proof_claimed", sa.Boolean, nullable=False),
        at("recorded_at"),
        sa.CheckConstraint(
            "amount_minor>0", name="ck_accompaniment_report_amount"
        ),
    )
    applications = sa.Table(
        "financial_accompaniment_refund_applications",
        metadata,
        uid("application_id", primary_key=True),
        uid(
            "observation_id",
            "financial_accompaniment_refund_observations.observation_id",
            nullable=False,
            unique=True,
        ),
        uid("paid_item_id", "order_items.paid_item_id", nullable=False),
        uid("payment_id", "payments.payment_id", nullable=False),
        uid("assignment_id", "item_assignments.assignment_id", nullable=True),
        sa.Column("work_version", sa.BigInteger, nullable=False),
        sa.Column("stage", sa.String, nullable=True),
        sa.Column(
            "policy_version",
            sa.String,
            sa.ForeignKey("financial_policy_versions.version"),
            nullable=False,
        ),
        sa.Column("rules", json, nullable=False),
        sa.Column("customer_target_minor", sa.BigInteger, nullable=False),
        sa.Column("customer_delta_minor", sa.BigInteger, nullable=False),
        sa.Column("manager_target_minor", sa.BigInteger, nullable=False),
        sa.Column("manager_delta_minor", sa.BigInteger, nullable=False),
        uid("actor_id", "users.user_id", nullable=False),
        text("reason"),
        text("evidence_reference"),
        text("evidence_hash"),
        at("recorded_at"),
        sa.CheckConstraint(
            "customer_target_minor>0 "
            "AND customer_delta_minor>0 "
            "AND customer_delta_minor<=customer_target_minor "
            "AND manager_target_minor BETWEEN 0 AND 60000 "
            "AND manager_delta_minor BETWEEN 0 AND manager_target_minor "
            "AND ((work_version=0 AND assignment_id IS NULL "
            "AND stage IS NULL AND manager_target_minor=0) "
            "OR (work_version>0 AND assignment_id IS NOT NULL "
            "AND stage IS NOT NULL))",
            name="ck_accompaniment_application_values",
        ),
    )
    reviews = sa.Table(
        "financial_accompaniment_management_reviews",
        metadata,
        uid("review_id", primary_key=True),
        uid(
            "application_id",
            "financial_accompaniment_refund_applications.application_id",
            nullable=False,
        ),
        uid("paid_item_id", "order_items.paid_item_id", nullable=False),
        uid("assignment_id", "item_assignments.assignment_id", nullable=False),
        sa.Column("work_version", sa.BigInteger, nullable=False),
        text("decision"),
        sa.Column("customer_net_minor", sa.BigInteger, nullable=False),
        uid("source_event_id", nullable=False, unique=True),
        uid("actor_id", "users.user_id", nullable=False),
        text("reason"),
        text("evidence_reference"),
        text("evidence_hash"),
        at("recorded_at"),
        sa.UniqueConstraint("assignment_id", "work_version"),
        sa.CheckConstraint(
            (
                "decision IN ('continue','cancel') AND "
                "customer_net_minor>=0 AND work_version>0"
            ),
            name="ck_accompaniment_management_review",
        ),
    )
    return {
        "commands": commands,
        "observations": observations,
        "applications": applications,
        "management_reviews": reviews,
    }


APPLICATION_GUARD = """
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
 IF observation.observation_id IS NULL OR item.accompaniment_minor IS DISTINCT
FROM COALESCE((policy.rules->>'accompaniment_minor')::bigint,120000)
 OR NEW.customer_target_minor>item.accompaniment_minor
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
 SELECT COALESCE(sum(customer_delta_minor),0),
 COALESCE(max(manager_target_minor),0)
 INTO prior_customer,prior_manager FROM
financial_accompaniment_refund_applications
 WHERE paid_item_id=NEW.paid_item_id AND application_id<>NEW.application_id;
 IF NEW.customer_delta_minor<>NEW.customer_target_minor-prior_customer
 OR NEW.manager_target_minor<prior_manager
 THEN RAISE EXCEPTION 'accompaniment_refund_cumulative_mismatch' USING
ERRCODE='23514'; END IF;
 IF NEW.stage<>'disputed' AND NEW.rules->'accompaniment_refund_rates_bps' ?
NEW.stage THEN
   stage_bps :=
(NEW.rules->'accompaniment_refund_rates_bps'->>NEW.stage)::integer;
   expected_customer :=
floor((item.accompaniment_minor::numeric*stage_bps+5000)/10000)::bigint;
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
  IF stage_bps IS NOT NULL THEN
   expected_manager:=(60000::bigint*stage_bps+5000)/10000;
  ELSE
expected_manager:=floor((60000::numeric*NEW.customer_target_minor+item.accompaniment_minor::numeric/2)/item.accompaniment_minor)::bigint;
  END IF;
 ELSE expected_manager:=NEW.manager_target_minor; END IF;
 IF NEW.manager_target_minor<>expected_manager THEN
  RAISE EXCEPTION 'accompaniment_manager_policy_mismatch' USING
ERRCODE='23514'; END IF;
 SELECT COALESCE(sum(m.amount_minor),0) INTO prior_manager
 FROM financial_movements m WHERE m.obligation_id=manager.id
 AND m.movement_type IN ('reversal','debt')
 AND m.refund_id IS DISTINCT FROM NEW.application_id;
 IF NEW.manager_delta_minor<>
 greatest(0,NEW.manager_target_minor-prior_manager) THEN
  RAISE EXCEPTION 'accompaniment_refund_cumulative_mismatch' USING
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


def accompaniment_refund_guards(tables):
    statements = [APPLICATION_GUARD, MANAGEMENT_REVIEW_GUARD]
    for table in tables.values():
        statements.append(
            "CREATE TRIGGER accompaniment_refund_immutable BEFORE UPDATE OR "
            f"DELETE OR TRUNCATE ON {table.name} FOR EACH STATEMENT "
            "EXECUTE FUNCTION financial_selection_deny_mutation();"
        )
    statements.append(
        "CREATE CONSTRAINT TRIGGER accompaniment_refund_application_guard "
        "AFTER INSERT ON financial_accompaniment_refund_applications "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION "
        "accompaniment_refund_check_application();"
    )
    statements.append(
        (
            "CREATE CONSTRAINT TRIGGER accompaniment_management_review_guard "
            "AFTER INSERT ON financial_accompaniment_management_reviews "
            "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION "
            "accompaniment_management_check_review();"
        )
    )
    return "\n".join(statements)


MANAGEMENT_REVIEW_GUARD = """
CREATE OR REPLACE FUNCTION accompaniment_management_check_review() RETURNS
trigger
LANGUAGE plpgsql AS $$
DECLARE app record; source record; latest_target bigint;
BEGIN
 SELECT * INTO app FROM financial_accompaniment_refund_applications
 WHERE application_id=NEW.application_id;
 SELECT * INTO source FROM financial_collaboration_events
 WHERE event_id=NEW.source_event_id;
 SELECT max(customer_target_minor) INTO latest_target FROM
 financial_accompaniment_refund_applications WHERE
paid_item_id=NEW.paid_item_id;
 IF app.paid_item_id IS DISTINCT FROM NEW.paid_item_id
 OR app.customer_target_minor IS DISTINCT FROM latest_target
 OR NEW.customer_net_minor IS DISTINCT FROM (SELECT accompaniment_minor FROM
order_items WHERE paid_item_id=app.paid_item_id)-app.customer_target_minor
 OR source.event_type IS DISTINCT FROM
'financial.collaboration.management_reviewed'
 OR source.assignment_id IS DISTINCT FROM NEW.assignment_id
 OR source.version IS DISTINCT FROM NEW.work_version+1
 OR source.actor_id IS DISTINCT FROM NEW.actor_id
 OR source.parameters->>'evidence' IS DISTINCT FROM
   'accompaniment-management-review:'||NEW.review_id::text
 OR source.parameters->>'reason' IS DISTINCT FROM NEW.reason
 OR source.result_payload->>'paid_item_id' IS DISTINCT FROM
NEW.paid_item_id::text
 OR length(trim(NEW.reason))=0 OR length(trim(NEW.evidence_reference))=0
 OR NEW.evidence_hash !~ '^[0-9a-f]{64}$'
 OR NOT EXISTS(SELECT 1 FROM users WHERE user_id=NEW.actor_id AND admin=true
AND status='active')
 THEN RAISE EXCEPTION 'accompaniment_management_review_source_mismatch'
USING ERRCODE='23514'; END
IF;
 IF NEW.decision='continue' THEN
   IF NEW.customer_net_minor<60000 OR
source.result_payload#>>'{collaboration,state}'
     IN ('disputed','rejected','unconfirmed_expired') THEN
    RAISE EXCEPTION 'accompaniment_management_continuation_unfunded' USING
ERRCODE='23514'; END IF;
 ELSE
   IF source.result_payload#>>'{collaboration,state}' IN
('success_final','available')
   OR EXISTS(SELECT 1 FROM financial_obligations WHERE
paid_item_id=NEW.paid_item_id
     AND kind='management') THEN
    RAISE EXCEPTION 'accompaniment_earned_management_requires_compensation'
USING ERRCODE='23514';
END IF;
 END IF;
 RETURN NEW;
END $$;
"""
