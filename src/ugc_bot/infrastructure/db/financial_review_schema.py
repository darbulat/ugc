"""Immutable post-factum economic cases and proved journal applications."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


def financial_review_tables(metadata):
    json = sa.JSON().with_variant(JSONB(), "postgresql")

    def uid(name, target=None, **options):
        return sa.Column(
            name,
            UUID(as_uuid=True),
            *(
                [sa.ForeignKey(target, deferrable=True, initially="DEFERRED")]
                if target
                else []
            ),
            nullable=False,
            **options,
        )

    def txt(name):
        return sa.Column(name, sa.Text, nullable=False)

    def at(name):
        return sa.Column(name, sa.DateTime(timezone=True), nullable=False)

    commands = sa.Table(
        "financial_review_commands",
        metadata,
        uid("actor_id", "users.user_id"),
        txt("operation_key"),
        txt("payload_hash"),
        sa.Column("result", json, nullable=False),
        at("recorded_at"),
        sa.PrimaryKeyConstraint("actor_id", "operation_key"),
    )
    cases = sa.Table(
        "financial_review_cases",
        metadata,
        uid("case_id", primary_key=True),
        uid("obligation_id", "financial_obligations.id"),
        txt("business_key"),
        uid("paid_item_id", "order_items.paid_item_id"),
        uid("order_id", "orders.order_id"),
        uid("recipient_id", "users.user_id"),
        txt("currency"),
        uid("opened_by", "users.user_id"),
        txt("operation_key"),
        at("opened_at"),
        txt("opened_source_hash"),
        sa.Column("source_document", json, nullable=False),
        sa.Column("blocked_buckets", json, nullable=False),
        sa.Column("prior_cancelled_minor", sa.BigInteger, nullable=False),
        txt("reason"),
        txt("evidence_reference"),
        txt("evidence_hash"),
        sa.UniqueConstraint("opened_by", "operation_key"),
        sa.ForeignKeyConstraint(
            ["opened_by", "operation_key"],
            [
                "financial_review_commands.actor_id",
                "financial_review_commands.operation_key",
            ],
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.CheckConstraint(
            "currency='RUB' AND prior_cancelled_minor>=0",
            name="ck_financial_review_case",
        ),
    )
    resolutions = sa.Table(
        "financial_review_resolutions",
        metadata,
        uid("case_id", "financial_review_cases.case_id", primary_key=True),
        sa.Column("version", sa.Integer, nullable=False),
        uid("actor_id", "users.user_id"),
        txt("operation_key"),
        txt("expected_source_hash"),
        txt("decision"),
        sa.Column("target_minor", sa.BigInteger, nullable=False),
        sa.Column("prior_cancelled_minor", sa.BigInteger, nullable=False),
        sa.Column("cancelled_delta_minor", sa.BigInteger, nullable=False),
        sa.Column("debt_created_minor", sa.BigInteger, nullable=False),
        sa.Column("release_at", sa.DateTime(timezone=True)),
        sa.Column("restored_buckets", json, nullable=False),
        txt("reason"),
        txt("evidence_reference"),
        txt("evidence_hash"),
        at("resolved_at"),
        sa.UniqueConstraint("actor_id", "operation_key"),
        sa.ForeignKeyConstraint(
            ["actor_id", "operation_key"],
            [
                "financial_review_commands.actor_id",
                "financial_review_commands.operation_key",
            ],
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.CheckConstraint(
            "version=2 AND decision IN ('no_adjustment','cumulative_cancel') "
            "AND prior_cancelled_minor>=0 "
            "AND target_minor>=prior_cancelled_minor "
            "AND cancelled_delta_minor=target_minor-prior_cancelled_minor "
            "AND debt_created_minor BETWEEN 0 AND cancelled_delta_minor",
            name="ck_financial_review_resolution",
        ),
    )
    return dict(commands=commands, cases=cases, resolutions=resolutions)


REVIEW_SQL = """
CREATE OR REPLACE FUNCTION financial_review_document(ground uuid) RETURNS jsonb
LANGUAGE sql STABLE AS $$
 SELECT jsonb_build_object(
 'original',correction_approval_row(to_jsonb(o),'financial_obligations'),
 'snapshot',correction_approval_row(to_jsonb(s),'rate_snapshots'),
 'capture',jsonb_build_object('event_id',e.event_id,'event_type',e.event_type,
 'aggregate_type',e.aggregate_type,'aggregate_id',e.aggregate_id,'payload',e.payload),
 'journal',COALESCE((SELECT jsonb_agg(correction_approval_row(to_jsonb(m),
 'financial_movements') ORDER BY m.append_order) FROM financial_movements m
 WHERE m.obligation_id=o.id),'[]'::jsonb))
 FROM financial_obligations o JOIN rate_snapshots s ON s.id=o.snapshot_id
 JOIN outbox_events e ON e.event_type='financial.client_snapshot_requested'
 AND e.aggregate_type='order' AND e.aggregate_id=o.order_id::text
 AND e.payload->>'payment_id'=s.payment_id::text
 WHERE o.id=ground
$$;
CREATE OR REPLACE FUNCTION financial_review_restores(blocked jsonb,
 removed bigint, release_time timestamptz, at_time timestamptz) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE bucket text; destination text; original bigint; taken bigint;
 result jsonb := '{"pending":0,"hold":0,"available":0}'::jsonb;
BEGIN
 FOREACH bucket IN ARRAY ARRAY['pending','hold','available'] LOOP
  original := (blocked->>bucket)::bigint;
  taken := LEAST(original,removed); removed := removed-taken;
  destination := bucket;
  IF bucket='available' AND (release_time IS NULL OR at_time<release_time)
   THEN destination:='hold'; END IF;
  result := jsonb_set(result,ARRAY[destination],to_jsonb(
   (result->>destination)::bigint+original-taken));
 END LOOP;
 RETURN result;
END $$;
CREATE OR REPLACE FUNCTION financial_review_before_case() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE o record; doc jsonb; bucket text; amount bigint; cancelled bigint;
BEGIN
 SELECT * INTO o FROM financial_obligations WHERE id=NEW.obligation_id;
 PERFORM 1 FROM order_items WHERE paid_item_id=NEW.paid_item_id FOR UPDATE;
 doc := financial_review_document(NEW.obligation_id);
 IF doc IS NULL OR NEW.source_document IS DISTINCT FROM doc
 OR NEW.opened_source_hash IS DISTINCT FROM correction_approval_hash(doc)
 OR (o.business_key,o.paid_item_id,o.order_id,o.recipient_id,o.currency)
 IS DISTINCT FROM (NEW.business_key,NEW.paid_item_id,NEW.order_id,
 NEW.recipient_id,NEW.currency)
 OR NOT EXISTS(SELECT 1 FROM users WHERE user_id=NEW.opened_by
 AND admin=true AND status='active')
 OR length(trim(NEW.reason))=0 OR length(trim(NEW.evidence_reference))=0
 OR NEW.evidence_hash !~ '^[0-9a-f]{64}$'
 OR EXISTS(SELECT 1 FROM financial_movements WHERE obligation_id=o.id
 AND recorded_at>NEW.opened_at) THEN
 RAISE EXCEPTION 'financial_review_source_changed' USING ERRCODE='23514';
 END IF;
 IF EXISTS(SELECT 1 FROM financial_review_cases c WHERE c.obligation_id=o.id
 AND NOT EXISTS(SELECT 1 FROM financial_review_resolutions r
 WHERE r.case_id=c.case_id)) THEN
 RAISE EXCEPTION 'financial_review_already_open' USING ERRCODE='23514'; END IF;
 IF jsonb_typeof(NEW.blocked_buckets) IS DISTINCT FROM 'object'
 OR (SELECT count(*) FROM jsonb_object_keys(NEW.blocked_buckets))<>3 THEN
 RAISE EXCEPTION 'financial_review_block_mismatch' USING ERRCODE='23514';
 END IF;
 FOREACH bucket IN ARRAY ARRAY['pending','hold','available'] LOOP
  SELECT COALESCE(sum(CASE WHEN bucket_to=bucket THEN amount_minor ELSE 0 END
  - CASE WHEN bucket_from=bucket THEN amount_minor ELSE 0 END),0)
  INTO amount FROM financial_movements WHERE obligation_id=o.id;
  IF NEW.blocked_buckets->>bucket IS NULL
  OR NEW.blocked_buckets->>bucket !~ '^[0-9]+$'
  OR (NEW.blocked_buckets->>bucket)::bigint<>amount THEN
  RAISE EXCEPTION 'financial_review_block_mismatch' USING ERRCODE='23514';
  END IF;
 END LOOP;
 SELECT COALESCE(sum(amount_minor),0) INTO cancelled FROM financial_movements
 WHERE obligation_id=o.id AND movement_type IN ('reversal','debt');
 IF NEW.prior_cancelled_minor<>cancelled OR cancelled>=o.amount_minor THEN
 RAISE EXCEPTION 'financial_review_no_liability' USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
"""


RESTORATION_SQL = """
CREATE OR REPLACE FUNCTION financial_review_blocked_cancelled(
 ground uuid, opening jsonb) RETURNS bigint LANGUAGE sql STABLE AS $$
 SELECT COALESCE(sum(m.amount_minor),0) FROM financial_movements m
 WHERE m.obligation_id=ground AND m.movement_type='reversal'
 AND m.bucket_from='blocked' AND NOT EXISTS(
  SELECT 1 FROM jsonb_array_elements(opening->'journal') old
  WHERE old->>'operation_key'=m.operation_key)
$$;
CREATE OR REPLACE FUNCTION financial_review_before_resolution() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE c record; o record; prior bigint; maturity timestamptz;
 liquid bigint; blocked_balance bigint; removed bigint;
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
 SELECT COALESCE(sum(
  CASE WHEN bucket_to IN ('pending','hold','available')
   THEN amount_minor ELSE 0 END-
  CASE WHEN bucket_from IN ('pending','hold','available')
   THEN amount_minor ELSE 0 END),0),
  COALESCE(sum(CASE WHEN bucket_to='blocked' THEN amount_minor ELSE 0 END-
   CASE WHEN bucket_from='blocked' THEN amount_minor ELSE 0 END),0)
 INTO liquid,blocked_balance FROM financial_movements
 WHERE obligation_id=c.obligation_id;
 removed:=financial_review_blocked_cancelled(c.obligation_id,c.source_document)
  +LEAST(blocked_balance,GREATEST(0,NEW.target_minor-prior-liquid));
 IF NEW.release_at IS DISTINCT FROM maturity
 OR NEW.restored_buckets IS DISTINCT FROM financial_review_restores(
 c.blocked_buckets,removed,maturity,NEW.resolved_at) THEN
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
 IF r.restored_buckets IS DISTINCT FROM financial_review_restores(
 c.blocked_buckets,financial_review_blocked_cancelled(
 c.obligation_id,c.source_document),r.release_at,r.resolved_at) THEN
 RAISE EXCEPTION 'financial_review_restore_application_mismatch'
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


def financial_review_guards(tables):
    sql = [REVIEW_SQL, RESTORATION_SQL, MOVEMENT_SQL]
    for table in tables.values():
        sql.append(
            "CREATE TRIGGER financial_review_immutable "
            f"BEFORE UPDATE OR DELETE OR TRUNCATE ON {table.name} "
            "FOR EACH STATEMENT EXECUTE FUNCTION "
            "financial_selection_deny_mutation();"
        )
    sql += [
        "CREATE TRIGGER financial_review_source BEFORE INSERT "
        "ON financial_review_cases FOR EACH ROW "
        "EXECUTE FUNCTION financial_review_before_case();",
        "CREATE TRIGGER financial_review_resolution_source BEFORE INSERT "
        "ON financial_review_resolutions FOR EACH ROW "
        "EXECUTE FUNCTION financial_review_before_resolution();",
        "CREATE CONSTRAINT TRIGGER financial_review_application AFTER INSERT "
        "ON financial_review_cases DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
        "EXECUTE FUNCTION financial_review_check_application();",
        "CREATE CONSTRAINT TRIGGER financial_review_resolution_application "
        "AFTER INSERT ON financial_review_resolutions DEFERRABLE INITIALLY "
        "DEFERRED FOR EACH ROW "
        "EXECUTE FUNCTION financial_review_check_application();",
    ]
    return "\n".join(sql)


MOVEMENT_SQL = """
CREATE OR REPLACE FUNCTION financial_review_check_movement() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE c record; r record; bucket text; amount bigint; used bigint;
BEGIN
 SELECT * INTO c FROM financial_review_cases WHERE case_id=NEW.case_id;
 IF c.case_id IS NULL THEN
  IF strpos(NEW.operation_key,'financial-review:')=1 OR EXISTS(
   SELECT 1 FROM financial_review_cases WHERE case_id=NEW.refund_id) THEN
   RAISE EXCEPTION 'financial_review_movement_authority_required'
   USING ERRCODE='23514'; END IF;
  RETURN NEW;
 END IF;
 IF NEW.obligation_id<>c.obligation_id OR NEW.currency<>c.currency THEN
 RAISE EXCEPTION 'financial_review_movement_scope_mismatch'
 USING ERRCODE='23514'; END IF;
 IF NEW.movement_type='recovery' THEN RETURN NEW; END IF;
 IF strpos(NEW.operation_key,'financial-review:'||c.case_id::text||':block:')=1
 THEN
  bucket:=NEW.bucket_from;
  IF bucket NOT IN ('pending','hold','available') OR NEW.bucket_to<>'blocked'
  OR NEW.operation_key<>'financial-review:'||c.case_id::text||':block:'||bucket
  OR NEW.movement_type<>'transfer' OR NEW.actor_kind<>'admin'
  OR NEW.actor_id IS DISTINCT FROM c.opened_by
  OR NEW.amount_minor IS DISTINCT FROM (c.blocked_buckets->>bucket)::bigint
  OR NEW.effective_at<>c.opened_at OR NEW.recorded_at<>c.opened_at
  OR EXISTS(SELECT 1 FROM financial_review_resolutions WHERE case_id=c.case_id)
  THEN RAISE EXCEPTION 'financial_review_block_movement_mismatch'
   USING ERRCODE='23514'; END IF;
  RETURN NEW;
 END IF;
 SELECT * INTO r FROM financial_review_resolutions WHERE case_id=c.case_id;
 IF r.case_id IS NULL OR NEW.actor_kind<>'admin'
 OR NEW.actor_id IS DISTINCT FROM r.actor_id
 OR NEW.effective_at<>r.resolved_at OR NEW.recorded_at<>r.resolved_at THEN
 RAISE EXCEPTION 'financial_review_resolution_authority_required'
 USING ERRCODE='23514'; END IF;
 IF NEW.movement_type IN ('reversal','debt') THEN
  SELECT COALESCE(sum(amount_minor),0) INTO used FROM financial_movements
  WHERE refund_id=c.case_id AND movement_type IN ('reversal','debt');
  IF NEW.refund_id IS DISTINCT FROM c.case_id
  OR r.decision<>'cumulative_cancel'
  OR used+NEW.amount_minor>r.cancelled_delta_minor THEN
  RAISE EXCEPTION 'financial_review_cancellation_mismatch'
  USING ERRCODE='23514'; END IF;
  RETURN NEW;
 END IF;
 bucket:=NEW.bucket_to;
 amount:=(r.restored_buckets->>bucket)::bigint;
 IF NEW.movement_type<>'transfer' OR NEW.bucket_from<>'blocked'
 OR bucket NOT IN ('pending','hold','available') OR amount IS NULL
 OR NEW.amount_minor<>amount
 OR NEW.operation_key<>'financial-review:'||c.case_id::text||':restore:'||bucket
 OR (bucket='available' AND (r.release_at IS NULL
   OR NEW.recorded_at<r.release_at OR NEW.effective_at<r.release_at)) THEN
 RAISE EXCEPTION 'financial_review_restore_movement_mismatch'
 USING ERRCODE='23514'; END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER financial_review_movement_source BEFORE INSERT
 ON financial_movements FOR EACH ROW
 EXECUTE FUNCTION financial_review_check_movement();
CREATE OR REPLACE FUNCTION financial_review_check_recovery() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.movement_type='recovery' AND EXISTS(
 SELECT 1 FROM financial_review_cases WHERE case_id=NEW.case_id)
 AND NOT EXISTS(SELECT 1 FROM financial_repayment_applications
 WHERE movement_id=NEW.id AND case_id=NEW.case_id) THEN
 RAISE EXCEPTION 'financial_review_actual_repayment_required'
 USING ERRCODE='23514'; END IF;
 RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER financial_review_recovery_source AFTER INSERT
 ON financial_movements DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
 EXECUTE FUNCTION financial_review_check_recovery();
"""
