"""Append-only incoming repayments and source-bound recovery applications."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID


def debt_recovery_tables(metadata):
    json = sa.JSON().with_variant(JSONB(), "postgresql")
    commands = sa.Table(
        "financial_repayment_commands",
        metadata,
        sa.Column(
            "command_id", UUID(as_uuid=True), nullable=False, unique=True
        ),
        sa.Column(
            "actor_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.user_id"),
            primary_key=True,
        ),
        sa.Column("operation_key", sa.String(256), primary_key=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("payload", json, nullable=False),
        sa.Column("result", json, nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "action IN ('RecordDebtRepayment','ApplyDebtRecovery')",
            name="ck_repayment_command_action",
        ),
    )
    observations = sa.Table(
        "financial_repayment_observations",
        metadata,
        sa.Column("observation_id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "command_id",
            UUID(as_uuid=True),
            sa.ForeignKey(
                "financial_repayment_commands.command_id",
                deferrable=True,
                initially="DEFERRED",
            ),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "recipient_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.user_id"),
            nullable=False,
        ),
        sa.Column("case_id", UUID(as_uuid=True), nullable=False),
        sa.Column("amount_minor", sa.BigInteger, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("proof_claimed", sa.Boolean, nullable=False),
        sa.Column("document", json, nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "amount_minor>0 AND currency='RUB'", name="ck_repayment_money"
        ),
    )
    applications = sa.Table(
        "financial_repayment_applications",
        metadata,
        sa.Column("application_id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "observation_id",
            UUID(as_uuid=True),
            sa.ForeignKey("financial_repayment_observations.observation_id"),
            nullable=False,
        ),
        sa.Column(
            "command_id",
            UUID(as_uuid=True),
            sa.ForeignKey(
                "financial_repayment_commands.command_id",
                deferrable=True,
                initially="DEFERRED",
            ),
            nullable=False,
        ),
        sa.Column(
            "obligation_id",
            UUID(as_uuid=True),
            sa.ForeignKey("financial_obligations.id"),
            nullable=False,
        ),
        sa.Column("case_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "recipient_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.user_id"),
            nullable=False,
        ),
        sa.Column("amount_minor", sa.BigInteger, nullable=False),
        sa.Column(
            "movement_id",
            UUID(as_uuid=True),
            sa.ForeignKey("financial_movements.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "source_entry_id",
            UUID(as_uuid=True),
            sa.ForeignKey("financial_movements.id"),
            nullable=False,
        ),
        sa.Column("result", json, nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "amount_minor>0", name="ck_repayment_application_money"
        ),
        sa.UniqueConstraint(
            "observation_id",
            "obligation_id",
            name="uq_repayment_observation_ground",
        ),
    )
    return commands, observations, applications


def debt_recovery_guards():
    return """
CREATE OR REPLACE FUNCTION repayment_deny_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
 RAISE EXCEPTION 'repayment_fact_immutable' USING ERRCODE='23514'; END $$;
CREATE TRIGGER repayment_command_immutable BEFORE UPDATE OR DELETE OR TRUNCATE
 ON financial_repayment_commands FOR EACH STATEMENT
 EXECUTE FUNCTION repayment_deny_mutation();
CREATE TRIGGER repayment_observation_immutable BEFORE UPDATE OR DELETE
 OR TRUNCATE ON financial_repayment_observations FOR EACH STATEMENT
 EXECUTE FUNCTION repayment_deny_mutation();
CREATE TRIGGER repayment_application_immutable BEFORE UPDATE OR DELETE
 OR TRUNCATE ON financial_repayment_applications FOR EACH STATEMENT
 EXECUTE FUNCTION repayment_deny_mutation();
CREATE OR REPLACE FUNCTION repayment_check_authority() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
 IF NOT EXISTS(SELECT1 FROM users WHERE user_id=NEW.actor_id
     AND status='active' AND admin=true) THEN
  RAISE EXCEPTION 'repayment_active_admin_required'; END IF;
 IF NEW.payload->>'actor_id' IS DISTINCT FROM NEW.actor_id::text
    OR NEW.payload->>'operation_key' IS DISTINCT FROM NEW.operation_key
    OR jsonb_typeof(NEW.payload) IS DISTINCT FROM 'object'
    OR jsonb_typeof(NEW.payload->'reason') IS DISTINCT FROM 'string'
    OR length(trim(COALESCE(NEW.payload->>'reason','')))=0
    OR jsonb_typeof(NEW.payload->'evidence_reference') IS DISTINCT FROM 'string'
    OR length(trim(COALESCE(NEW.payload->>'evidence_reference','')))=0
    OR jsonb_typeof(NEW.payload->'evidence_hash') IS DISTINCT FROM 'string'
    OR (NEW.payload->>'evidence_hash') !~ '^[0-9a-f]{64}$' THEN
  RAISE EXCEPTION 'repayment_command_scope_mismatch'; END IF;
 RETURN NEW; END $$;
CREATE TRIGGER repayment_command_authority BEFORE INSERT
 ON financial_repayment_commands FOR EACH ROW
 EXECUTE FUNCTION repayment_check_authority();
CREATE OR REPLACE FUNCTION repayment_check_observation() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE c record;
BEGIN
 SELECT * INTO c FROM financial_repayment_commands
  WHERE command_id=NEW.command_id;
 IF c.command_id IS NULL OR c.action IS DISTINCT FROM 'RecordDebtRepayment'
  OR NEW.document - ARRAY['observation_id','command_id','proof_claimed',
       'blocker','identity','recorded_at'] IS DISTINCT FROM c.payload
  OR NEW.document->>'observation_id' IS DISTINCT FROM NEW.observation_id::text
  OR NEW.document->>'command_id' IS DISTINCT FROM NEW.command_id::text
  OR NEW.document->>'recipient_id' IS DISTINCT FROM NEW.recipient_id::text
  OR NEW.document->>'case_id' IS DISTINCT FROM NEW.case_id::text
  OR (NEW.document->>'amount_minor')::bigint
       IS DISTINCT FROM NEW.amount_minor
  OR NEW.document->>'currency' IS DISTINCT FROM NEW.currency
  OR (NEW.document->>'proof_claimed')::boolean
       IS DISTINCT FROM NEW.proof_claimed
  OR (NEW.document->>'recorded_at')::timestamptz
       IS DISTINCT FROM NEW.recorded_at
  OR jsonb_typeof(NEW.document->'occurred_at') IS DISTINCT FROM 'string'
  OR NEW.document->>'occurred_at' IS NULL
  OR jsonb_typeof(NEW.document->'amount_minor') IS DISTINCT FROM 'number'
  OR (NEW.document->>'amount_minor') !~ '^[1-9][0-9]*$'
  OR jsonb_typeof(NEW.document->'bank_account_label') IS DISTINCT FROM 'string'
  OR length(trim(COALESCE(NEW.document->>'bank_account_label','')))=0
  OR jsonb_typeof(NEW.document->'bank_reference') IS DISTINCT FROM 'string'
  OR length(trim(COALESCE(NEW.document->>'bank_reference','')))=0
  OR (NEW.document->>'occurred_at')::timestamptz>NEW.recorded_at
  OR NEW.recorded_at>c.recorded_at
  OR c.result->>'observation_id' IS DISTINCT FROM NEW.observation_id::text
  OR (c.result->>'proof_claimed')::boolean
       IS DISTINCT FROM NEW.proof_claimed THEN
  RAISE EXCEPTION 'repayment_observation_source_mismatch'
   USING ERRCODE='23514'; END IF;
 RETURN NULL; END $$;
CREATE CONSTRAINT TRIGGER repayment_observation_source AFTER INSERT
 ON financial_repayment_observations DEFERRABLE INITIALLY DEFERRED
 FOR EACH ROW EXECUTE FUNCTION repayment_check_observation();
CREATE OR REPLACE FUNCTION repayment_check_source() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE o record; c record; m record; b record; v bigint; n integer;
 total_applied bigint; applications jsonb; first_application text;
BEGIN
 SELECT * INTO o FROM financial_repayment_observations
  WHERE observation_id=NEW.observation_id;
 SELECT * INTO c FROM financial_repayment_commands
  WHERE command_id=NEW.command_id;
 SELECT * INTO m FROM financial_movements WHERE id=NEW.movement_id;
 SELECT * INTO b FROM financial_obligations WHERE id=NEW.obligation_id;
 IF o.observation_id IS NULL OR c.command_id IS NULL
  OR NOT o.proof_claimed OR c.action IS DISTINCT FROM 'ApplyDebtRecovery'
  OR (o.recipient_id,o.case_id,o.currency)
    IS DISTINCT FROM (NEW.recipient_id,NEW.case_id,b.currency)
  OR b.recipient_id IS DISTINCT FROM NEW.recipient_id
  OR o.recorded_at>NEW.recorded_at
  OR NEW.result IS DISTINCT FROM c.result
  OR (m.actor_kind,m.reason,m.currency,m.effective_at,m.recorded_at)
    IS DISTINCT FROM ('admin'::text,c.payload->>'reason',o.currency,
       NEW.recorded_at,NEW.recorded_at)
  OR (o.document->>'occurred_at')::timestamptz>o.recorded_at
  OR (m.obligation_id,m.case_id,m.amount_minor,m.movement_type,m.actor_id,
      m.source_entry_id,m.bucket_from,m.bucket_to,m.operation_key)
   IS DISTINCT FROM (NEW.obligation_id,NEW.case_id,NEW.amount_minor,
      'recovery'::text,c.actor_id,NEW.source_entry_id,NULL::text,NULL::text,
      'repayment:'||NEW.observation_id::text||':'||NEW.obligation_id::text)
  OR m.event_id IS DISTINCT FROM NEW.observation_id::text
  OR NOT EXISTS(SELECT1 FROM financial_obligations anchor
       JOIN financial_movements d ON d.obligation_id=anchor.id
       WHERE anchor.business_key=c.payload->>'business_key'
        AND anchor.recipient_id=NEW.recipient_id AND anchor.currency=o.currency
        AND d.case_id=NEW.case_id AND d.movement_type='debt')
  OR c.payload->>'case_id' IS DISTINCT FROM NEW.case_id::text
  OR c.payload->>'observation_id' IS DISTINCT FROM NEW.observation_id::text
  OR jsonb_typeof(c.payload->'expected_debt_minor') IS DISTINCT FROM 'number'
  OR (c.payload->>'expected_debt_minor') !~ '^[1-9][0-9]*$'
  OR NOT EXISTS(SELECT1 FROM financial_movements i WHERE
      i.id=NEW.source_entry_id AND i.obligation_id=NEW.obligation_id
      AND i.movement_type='issuance') THEN
  RAISE EXCEPTION 'repayment_application_source_mismatch'; END IF;
 SELECT count(*) INTO n FROM financial_physical_proof_claims p WHERE
  p.source=o.document->'identity'->>'source'
  AND p.account=o.document->'identity'->>'account'
  AND p.direction='incoming'
  AND p.reference=o.document->'identity'->>'reference'
  AND p.producer='repayment' AND p.intent_id=o.observation_id
  AND p.observation_id=o.observation_id AND p.command_id=o.command_id;
 IF n<>1 THEN RAISE EXCEPTION 'repayment_physical_proof_required'; END IF;
 -- Reconstruct the whole case immediately before this observation's group.
 SELECT COALESCE(sum(CASE WHEN fm.movement_type='debt' THEN fm.amount_minor
   WHEN fm.movement_type='recovery' THEN -fm.amount_minor ELSE0 END),0) INTO v
 FROM financial_movements fm
 JOIN financial_obligations g ON g.id=fm.obligation_id
 WHERE g.recipient_id=NEW.recipient_id AND g.currency=o.currency
  AND fm.case_id=NEW.case_id
  AND NOT EXISTS(SELECT1 FROM financial_repayment_applications a
    WHERE a.observation_id=NEW.observation_id AND a.movement_id=fm.id);
 SELECT sum(a.amount_minor), jsonb_agg(jsonb_build_object(
   'application_id',a.application_id::text,'obligation_id',a.obligation_id::text,
   'recovered_minor',a.amount_minor) ORDER BY a.obligation_id),
   (array_agg(a.application_id::text ORDER BY a.obligation_id))[1]
 INTO total_applied,applications,first_application
 FROM financial_repayment_applications a
 WHERE a.observation_id=NEW.observation_id;
 IF total_applied IS DISTINCT FROM o.amount_minor
  OR (NEW.result->>'recovered_minor')::bigint IS DISTINCT FROM o.amount_minor
  OR (NEW.result->>'remaining_debt_minor')::bigint
     IS DISTINCT FROM v-o.amount_minor
  OR v IS DISTINCT FROM (c.payload->>'expected_debt_minor')::bigint
  OR o.amount_minor>v
  OR NEW.result->'applications' IS DISTINCT FROM applications
  OR NEW.result->>'application_id' IS DISTINCT FROM first_application
  OR NEW.result->>'observation_id' IS DISTINCT FROM NEW.observation_id::text
  OR NEW.result->>'case_id' IS DISTINCT FROM NEW.case_id::text
  OR NEW.result->>'business_key' IS DISTINCT FROM c.payload->>'business_key'
  OR (NEW.result->>'applied')::boolean IS DISTINCT FROM true
  OR EXISTS(SELECT1 FROM financial_repayment_applications a
      WHERE a.observation_id=NEW.observation_id
       AND (a.command_id,a.case_id,a.recipient_id,a.recorded_at,a.result)
        IS DISTINCT FROM (NEW.command_id,NEW.case_id,NEW.recipient_id,
           NEW.recorded_at,NEW.result))
  OR EXISTS(SELECT1 FROM financial_movements d
      JOIN financial_obligations g ON g.id=d.obligation_id
      WHERE g.recipient_id=NEW.recipient_id AND g.currency=o.currency
       AND d.case_id=NEW.case_id AND d.movement_type='debt'
       AND d.recorded_at>NEW.recorded_at) THEN
  RAISE EXCEPTION 'repayment_exceeds_case_debt'; END IF;
 -- Canonical UUID order must exhaust each earlier ground before the next.
 WITH debts AS (
  SELECT g.id, sum(CASE WHEN fm.movement_type='debt' THEN fm.amount_minor
    WHEN fm.movement_type='recovery' THEN -fm.amount_minor ELSE0 END) debt_minor
  FROM financial_obligations g
  JOIN financial_movements fm ON fm.obligation_id=g.id
  WHERE g.recipient_id=NEW.recipient_id AND g.currency=o.currency
   AND fm.case_id=NEW.case_id
   AND NOT EXISTS(SELECT1 FROM financial_repayment_applications a
     WHERE a.observation_id=NEW.observation_id AND a.movement_id=fm.id)
  GROUP BY g.id
 ), ordered AS (
  SELECT id,debt_minor,COALESCE(sum(debt_minor) OVER (ORDER BY id
   ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING),0) prior_minor
  FROM debts WHERE debt_minor>0
 ), expected AS (
  SELECT id,LEAST(debt_minor,GREATEST(0,o.amount_minor-prior_minor))
   amount_minor
  FROM ordered
 ), actual AS (
  SELECT obligation_id id,amount_minor FROM financial_repayment_applications
   WHERE observation_id=NEW.observation_id
 )
 SELECT count(*) INTO n FROM
  (SELECT * FROM expected WHERE amount_minor>0) e FULL JOIN actual a USING(id)
 WHERE e.amount_minor IS DISTINCT FROM a.amount_minor;
 IF n<>0 THEN RAISE EXCEPTION 'repayment_allocation_mismatch'; END IF;
 RETURN NULL; END $$;
CREATE CONSTRAINT TRIGGER repayment_application_source AFTER INSERT
 ON financial_repayment_applications DEFERRABLE INITIALLY DEFERRED
 FOR EACH ROW EXECUTE FUNCTION repayment_check_source();
""".replace("SELECT1", "SELECT 1").replace("ELSE0", "ELSE 0")
