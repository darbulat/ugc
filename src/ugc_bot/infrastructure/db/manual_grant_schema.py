"""Separate positive expense authority; canonical rewards stay frozen."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

MANUAL_CHECKS = {
    "ck_obligation_kind": (
        "financial_obligations",
        (
            "kind IN "
            "('client_referral','creator_referral','management','manual_adjustment')"
        ),
    ),
    "ck_snapshot_policy": (
        "rate_snapshots",
        (
            "side IN ('client','creator','management','manual_adjustment') "
            "AND currency='RUB' AND age_rule IN "
            "('first_year','after_anniversary','management','manual_adjustment')"
            " AND (side IN ('management','manual_adjustment') OR "
            "effective_at>=registered_at)"
        ),
    ),
    "ck_snapshot_referral_fields_present": (
        "rate_snapshots",
        (
            "side IN ('management','manual_adjustment') OR (registered_at IS "
            "NOT NULL AND rate_bps IS NOT NULL)"
        ),
    ),
    "ck_snapshot_grade_applicable": (
        "rate_snapshots",
        (
            "verified_count IS NOT NULL OR side IN "
            "('client','management','manual_adjustment')"
        ),
    ),
}
MANUAL_FIELDS = (
    "side<>'manual_adjustment' OR (registered_at IS NULL AND "
    "verified_count IS NULL AND rate_bps IS NULL AND "
    "age_rule='manual_adjustment' AND assignment_id IS NULL AND "
    "rate_source='standard' AND override_id IS NULL)"
)


def extend_manual_grant_metadata(metadata):
    for name, (table_name, expression) in MANUAL_CHECKS.items():
        table = metadata.tables[table_name]
        for constraint in tuple(table.constraints):
            if constraint.name == name:
                table.constraints.remove(constraint)
        table.append_constraint(sa.CheckConstraint(expression, name=name))
    metadata.tables["rate_snapshots"].append_constraint(
        sa.CheckConstraint(MANUAL_FIELDS, name="ck_snapshot_manual_fields_na")
    )


def manual_grant_tables(metadata):
    json = sa.JSON().with_variant(JSONB(), "postgresql")

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

    def txt(name):
        return sa.Column(name, sa.Text, nullable=False)

    commands = sa.Table(
        "financial_manual_grant_commands",
        metadata,
        uid("actor_id", "users.user_id"),
        txt("operation_key"),
        txt("payload_hash"),
        sa.Column("result", json, nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("actor_id", "operation_key"),
    )
    grants = sa.Table(
        "financial_manual_grants",
        metadata,
        uid("grant_id", primary_key=True),
        uid("actor_id", "users.user_id"),
        txt("operation_key"),
        uid("recipient_id", "users.user_id"),
        uid("paid_item_id", "order_items.paid_item_id"),
        uid("order_id", "orders.order_id"),
        uid("client_id", "users.user_id"),
        uid("payment_id", "payments.payment_id"),
        uid("capture_id", "outbox_events.event_id"),
        sa.Column(
            "policy_version",
            sa.String,
            sa.ForeignKey("financial_policy_versions.version"),
            nullable=False,
        ),
        sa.Column("amount_minor", sa.BigInteger, nullable=False),
        txt("currency"),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("release_at", sa.DateTime(timezone=True), nullable=False),
        txt("reason"),
        txt("evidence_reference"),
        txt("evidence_hash"),
        txt("capture_source_hash"),
        sa.Column("authority", json, nullable=False),
        txt("authority_hash"),
        sa.UniqueConstraint("actor_id", "operation_key"),
        sa.ForeignKeyConstraint(
            ["actor_id", "operation_key"],
            [
                "financial_manual_grant_commands.actor_id",
                "financial_manual_grant_commands.operation_key",
            ],
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.CheckConstraint(
            "amount_minor>0 AND currency='RUB' AND release_at>approved_at",
            name="ck_manual_grant_values",
        ),
    )
    return {"commands": commands, "grants": grants}


MANUAL_GRANT_SCOPE_SQL = """
CREATE OR REPLACE FUNCTION ledger_check_obligation_scope() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE snapshot_side text; snapshot_assignment uuid;
BEGIN
 SELECT side,assignment_id INTO snapshot_side,snapshot_assignment
 FROM rate_snapshots WHERE id=NEW.snapshot_id;
 IF snapshot_assignment IS DISTINCT FROM NEW.assignment_id THEN
 RAISE EXCEPTION 'snapshot_assignment_mismatch' USING ERRCODE='23514'; END IF;
 IF snapshot_side IS DISTINCT FROM (CASE NEW.kind WHEN 'client_referral'
 THEN 'client' WHEN 'creator_referral' THEN 'creator' WHEN 'manual_adjustment'
 THEN 'manual_adjustment' ELSE 'management' END) THEN
 RAISE EXCEPTION 'snapshot_side_mismatch' USING ERRCODE='23514'; END IF;
 IF NEW.kind='manual_adjustment' AND NOT EXISTS(SELECT 1 FROM
financial_manual_grants g
 WHERE 'manual-grant:'||g.grant_id::text=NEW.business_key AND
(g.recipient_id,g.paid_item_id,g.order_id,g.policy_version,g.currency,g.amount_minor,g.release_at)
 IS NOT DISTINCT FROM
(NEW.recipient_id,NEW.paid_item_id,NEW.order_id,NEW.policy_version,NEW.currency,NEW.amount_minor,NEW.available_at)
 AND NEW.base_minor=g.amount_minor) THEN
 RAISE EXCEPTION 'manual_grant_approval_required' USING ERRCODE='23514'; END
IF;
 RETURN NEW;
END $$;
CREATE OR REPLACE FUNCTION manual_grant_check_source() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE capture record; payment record; item record; command record;
 original record; snapshot record; issuance record;
BEGIN
 SELECT * INTO capture FROM outbox_events WHERE event_id=NEW.capture_id;
 SELECT * INTO item FROM order_items WHERE paid_item_id=NEW.paid_item_id;
 SELECT * INTO payment FROM payments WHERE payment_id=NEW.payment_id;
 SELECT * INTO command FROM financial_manual_grant_commands
 WHERE actor_id=NEW.actor_id AND operation_key=NEW.operation_key;
 SELECT * INTO original FROM financial_obligations
 WHERE business_key='manual-grant:'||NEW.grant_id::text;
 SELECT * INTO snapshot FROM rate_snapshots WHERE id=original.snapshot_id;
 SELECT * INTO issuance FROM financial_movements
 WHERE operation_key='issue:'||original.business_key;
 IF capture.event_id IS NULL OR original.id IS NULL OR issuance.id IS NULL
 OR command.result->>'grant_id' IS DISTINCT FROM NEW.grant_id::text
 OR command.result->>'obligation_id' IS DISTINCT FROM original.id::text
 OR capture.event_type IS DISTINCT FROM 'financial.client_snapshot_requested'
 OR capture.aggregate_type IS DISTINCT FROM 'order'
 OR capture.aggregate_id IS DISTINCT FROM NEW.order_id::text
 OR capture.payload->>'payment_id' IS DISTINCT FROM NEW.payment_id::text
 OR capture.payload#>>'{capture,client_id}' IS DISTINCT FROM
NEW.client_id::text
 OR payment.order_id IS DISTINCT FROM NEW.order_id OR payment.paid_at IS NULL
 OR item.order_id IS DISTINCT FROM NEW.order_id
 OR item.policy_version IS DISTINCT FROM NEW.policy_version
 OR item.captured_at IS DISTINCT FROM payment.paid_at
 OR NEW.capture_source_hash IS DISTINCT FROM
correction_approval_hash(jsonb_build_object(
'event_id',capture.event_id,'event_type',capture.event_type,'aggregate_id',capture.aggregate_id,
 'aggregate_type',capture.aggregate_type,'payload',capture.payload))
 OR NEW.approved_at<payment.paid_at
 OR NEW.release_at<>NEW.approved_at+INTERVAL '14 days'
 OR jsonb_typeof(NEW.authority->'superadmin_user_ids') IS DISTINCT FROM
'array'
 OR (NEW.authority->'superadmin_user_ids' ? NEW.actor_id::text) IS NOT TRUE
 OR NEW.authority_hash IS DISTINCT FROM
correction_approval_hash(NEW.authority)
 OR NOT EXISTS(SELECT 1 FROM users WHERE user_id=NEW.actor_id AND admin=true
AND status='active')
 OR length(trim(NEW.reason))=0 OR length(trim(NEW.evidence_reference))=0
 OR NEW.evidence_hash !~ '^[0-9a-f]{64}$'
 OR original.kind IS DISTINCT FROM 'manual_adjustment'
 OR original.recipient_id IS DISTINCT FROM NEW.recipient_id
 OR original.base_minor IS DISTINCT FROM NEW.amount_minor
 OR original.amount_minor IS DISTINCT FROM NEW.amount_minor
 OR snapshot.side IS DISTINCT FROM 'manual_adjustment'
 OR snapshot.payment_id IS DISTINCT FROM NEW.payment_id
 OR snapshot.referred_user_id IS DISTINCT FROM NEW.client_id
 OR snapshot.effective_at IS DISTINCT FROM NEW.approved_at
 OR issuance.actor_id IS DISTINCT FROM NEW.actor_id OR issuance.actor_kind
IS DISTINCT FROM 'admin'
 OR issuance.event_id IS DISTINCT FROM NEW.grant_id::text
 OR issuance.movement_type IS DISTINCT FROM 'issuance'
 OR issuance.bucket_to IS DISTINCT FROM 'pending'
 OR issuance.amount_minor IS DISTINCT FROM NEW.amount_minor
 OR issuance.effective_at IS DISTINCT FROM NEW.approved_at
 OR issuance.recorded_at IS DISTINCT FROM NEW.approved_at
 THEN RAISE EXCEPTION 'manual_grant_source_mismatch' USING ERRCODE='23514';
END IF;
 RETURN NEW;
END $$;
CREATE OR REPLACE FUNCTION manual_grant_check_movement() RETURNS trigger
LANGUAGE plpgsql AS $$ DECLARE original record; grant_source record;
BEGIN
 SELECT * INTO original FROM financial_obligations WHERE id=NEW.obligation_id;
 IF original.kind<>'manual_adjustment' THEN RETURN NEW; END IF;
 SELECT * INTO grant_source FROM financial_manual_grants
 WHERE original.business_key='manual-grant:'||grant_id::text;
 IF grant_source.grant_id IS NULL OR NEW.currency<>'RUB'
 OR (NEW.bucket_to IN ('available','reserved','paid') AND
 (NEW.effective_at<grant_source.release_at
 OR NEW.recorded_at<grant_source.release_at)) THEN
 RAISE EXCEPTION 'manual_grant_hold_required' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
"""


def manual_grant_guards(tables):
    statements = [MANUAL_GRANT_SCOPE_SQL]
    for table in tables.values():
        statements.append(
            "CREATE TRIGGER manual_grant_immutable BEFORE UPDATE OR DELETE "
            f"OR TRUNCATE ON {table.name} FOR EACH STATEMENT EXECUTE "
            "FUNCTION financial_selection_deny_mutation();"
        )
    statements.append(
        (
            "CREATE CONSTRAINT TRIGGER manual_grant_source_guard AFTER INSERT"
            " ON financial_manual_grants DEFERRABLE INITIALLY DEFERRED FOR "
            "EACH ROW EXECUTE FUNCTION manual_grant_check_source();"
        )
    )
    statements.append(
        (
            "CREATE TRIGGER manual_grant_movement_guard BEFORE INSERT ON "
            "financial_movements FOR EACH ROW EXECUTE FUNCTION "
            "manual_grant_check_movement();"
        )
    )
    return "\n".join(statements)
