"""Additive immutable refund approvals and exact retained match provenance."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from ugc_bot.infrastructure.db.correction_schema import CURRENT_GUARD_SQL


def correction_approval_tables(metadata):
    def uid(name, target=None, *, primary_key=False):
        return sa.Column(
            name,
            UUID(as_uuid=True),
            *(
                [sa.ForeignKey(target, deferrable=True, initially="DEFERRED")]
                if target
                else []
            ),
            nullable=False,
            primary_key=primary_key,
        )

    json_type = sa.JSON().with_variant(JSONB(), "postgresql")
    approvals = sa.Table(
        "financial_refund_intent_approvals",
        metadata,
        uid("approval_id", primary_key=True),
        uid("intent_id", "financial_refund_intents.intent_id"),
        uid("case_id", "financial_correction_cases.case_id"),
        uid("command_id", "financial_correction_commands.command_id"),
        uid("request_id", "financial_correction_requests.request_id"),
        uid("client_id", "users.user_id"),
        uid("order_id", "orders.order_id"),
        uid("capture_id", "outbox_events.event_id"),
        uid("payment_id", "payments.payment_id"),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("source_capsule", json_type, nullable=False),
        sa.Column("bundle", json_type, nullable=False),
        sa.Column("amount_minor", sa.BigInteger, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("review_version", sa.BigInteger, nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("command_id"),
        sa.UniqueConstraint("intent_id", "review_version"),
        sa.ForeignKeyConstraint(
            ["case_id", "review_version"],
            [
                "financial_correction_events.case_id",
                "financial_correction_events.version",
            ],
            deferrable=True,
            initially="DEFERRED",
        ),
        sa.CheckConstraint(
            "source_hash ~ '^[0-9a-f]{64}$' AND currency='RUB' AND "
            "amount_minor>0 AND review_version>0 AND "
            "jsonb_typeof(source_capsule)='object' AND "
            "jsonb_typeof(bundle)='array' AND "
            "jsonb_array_length(bundle) BETWEEN 1 AND 200",
            name="ck_correction_approval_capsule",
        ),
    )
    links = sa.Table(
        "financial_refund_match_approvals",
        metadata,
        uid("match_id", "financial_refund_matches.match_id", primary_key=True),
        uid("approval_id", "financial_refund_intent_approvals.approval_id"),
    )
    tables = dict(approvals=approvals, match_approvals=links)
    for kind, table in tables.items():
        for column in table.c:
            if isinstance(column.type, UUID):
                table.append_constraint(
                    sa.CheckConstraint(
                        f"{column.name}<>'00000000-0000-0000-0000-000000000000'",
                        name=f"ck_correction_{kind}_{column.name}",
                    )
                )
    return tables


APPROVAL_SQL = r"""
CREATE OR REPLACE FUNCTION correction_approval_json(value jsonb) RETURNS text
LANGUAGE plpgsql IMMUTABLE STRICT AS $$
DECLARE result text;
BEGIN
 CASE jsonb_typeof(value)
 WHEN 'object' THEN SELECT '{'||COALESCE(string_agg(to_jsonb(key)::text||':'||
   correction_approval_json(val),',' ORDER BY key COLLATE "C"),'')||'}'
   INTO result FROM jsonb_each(value) AS x(key,val);
 WHEN 'array' THEN SELECT '['||COALESCE(string_agg(
   correction_approval_json(val),',' ORDER BY ord),'')||']'
   INTO result FROM jsonb_array_elements(value) WITH ORDINALITY AS x(val,ord);
 ELSE result := value::text;
 END CASE;
 RETURN result;
END $$;
CREATE OR REPLACE FUNCTION correction_approval_hash(value jsonb) RETURNS text
LANGUAGE sql IMMUTABLE STRICT AS $$ SELECT encode(sha256(convert_to(
 correction_approval_json(value-'id'-'recorded_at'-'payload_hash'),
 'UTF8')),'hex') $$;
CREATE OR REPLACE FUNCTION correction_approval_row(value jsonb, relation
 regclass)
RETURNS jsonb LANGUAGE sql STABLE STRICT AS $$
 SELECT jsonb_object_agg(x.key, CASE WHEN a.atttypid=1184 AND
 x.val<>'null'::jsonb
 THEN to_jsonb(to_char((x.val#>>'{}')::timestamptz AT TIME ZONE 'UTC',
 'YYYY-MM-DD"T"HH24:MI:SS.US')||'+00:00') ELSE x.val END)
 FROM jsonb_each(value) x(key,val) LEFT JOIN pg_attribute a
 ON a.attrelid=relation AND a.attname=x.key AND a.attnum>0 AND NOT
 a.attisdropped
$$;

CREATE OR REPLACE FUNCTION correction_approval_chain(selected_case uuid,
 through_version bigint) RETURNS boolean LANGUAGE sql STABLE AS $$
 SELECT count(*)=through_version AND COALESCE(bool_and(COALESCE(
 e.result_state->>'case_id'=e.case_id::text
 AND e.result_state->'version'=to_jsonb(e.version)
 AND e.result_state->>'source_hash'=e.source_hash
 AND e.result_state_hash=correction_approval_hash(e.result_state)
 AND (e.version=1 AND e.previous_state_hash IS NULL OR
 e.version>1 AND previous.version=e.version-1
 AND e.previous_state_hash=previous.result_state_hash)
 AND (e.version=1 OR (e.result_state->'observation_ids') @>
 (previous.result_state->'observation_ids'))
 ,false)),false) FROM financial_correction_events e
 LEFT JOIN financial_correction_events previous
 ON previous.case_id=e.case_id AND previous.version=e.version-1
 WHERE e.case_id=selected_case AND e.version<=through_version
$$;

CREATE OR REPLACE FUNCTION correction_validate_authority(authority jsonb)
RETURNS void LANGUAGE plpgsql AS $$
DECLARE intent record; request record; receipt record; reviewed record;
 ordered record; payment record; capture record; invoice record; intake record;
 item record; allocation record; policy record; b jsonb; expected jsonb;
 components jsonb; selected jsonb; normalized_bundle jsonb := '[]';
 actual_grounds jsonb; source_hash text; due_hash text; n integer;
 is_new boolean := authority ? 'approval_id';
BEGIN
 SELECT * INTO intent FROM financial_refund_intents
 WHERE intent_id=(authority->>'intent_id')::uuid;
 SELECT * INTO request FROM financial_correction_requests
 WHERE request_id=(authority->>'request_id')::uuid;
 SELECT * INTO ordered FROM orders WHERE order_id=request.order_id;
 IF intent.intent_id IS NULL OR request.request_id IS NULL
 OR intent.case_id IS DISTINCT FROM request.case_id
 OR authority->>'case_id' IS DISTINCT FROM request.case_id::text
 OR authority->>'currency' IS DISTINCT FROM 'RUB'
 OR authority->>'source_hash' IS DISTINCT FROM request.source_hash
 OR authority->'bundle' IS DISTINCT FROM request.bundle
 OR (is_new AND (authority->>'client_id' IS DISTINCT FROM
 request.client_id::text
     OR authority->>'order_id' IS DISTINCT FROM request.order_id::text))
 OR ordered.advertiser_id IS DISTINCT FROM request.client_id
 OR EXISTS (SELECT 1 FROM financial_correction_cases c WHERE
 c.case_id=request.case_id
   AND (c.client_id IS NOT NULL AND c.client_id<>request.client_id
     OR c.order_id IS NOT NULL AND c.order_id<>request.order_id))
 THEN RAISE EXCEPTION 'correction_approval_source_invalid' USING
 ERRCODE='23514'; END IF;
 SELECT * INTO receipt FROM financial_correction_commands
 WHERE command_id=request.command_id;
 SELECT count(*) INTO n FROM financial_correction_events e
 WHERE e.command_id=request.command_id AND e.source_id=request.request_id;
 IF receipt.action IS DISTINCT FROM 'RequestSelectionRefund'
 OR receipt.actor_id IS DISTINCT FROM request.client_id
 OR receipt.result->>'request_id' IS DISTINCT FROM request.request_id::text OR
 n<>1
 OR NOT EXISTS (SELECT 1 FROM financial_correction_events e
 WHERE e.command_id=request.command_id AND e.source_id=request.request_id
 AND e.case_id=request.case_id AND e.actor_id=request.client_id
 AND e.source_hash=request.source_hash AND receipt.result @> e.result_state
 AND e.result_state->>'case_id'=e.case_id::text
 AND e.result_state->'version'=to_jsonb(e.version)
 AND e.result_state->>'source_hash'=e.source_hash
 AND e.result_state_hash=correction_approval_hash(e.result_state))
 THEN RAISE EXCEPTION 'correction_request_authority_invalid' USING
 ERRCODE='23514'; END IF;
 SELECT * INTO receipt FROM financial_correction_commands
 WHERE command_id=(authority->>'command_id')::uuid;
 SELECT * INTO reviewed FROM financial_correction_events
 WHERE case_id=request.case_id AND
 version=(authority->>'review_version')::bigint;
 IF receipt.action IS DISTINCT FROM 'ReviewSelectionRefund'
 OR reviewed.command_id IS DISTINCT FROM receipt.command_id
 OR reviewed.actor_id IS DISTINCT FROM receipt.actor_id
 OR reviewed.source_id::text IS DISTINCT FROM
 COALESCE(authority->>'approval_id',authority->>'intent_id')
 OR reviewed.source_hash IS DISTINCT FROM authority->>'source_hash'
 OR reviewed.recorded_at IS DISTINCT FROM
 (authority->>'recorded_at')::timestamptz
 OR reviewed.result_state->>'review_status' IS DISTINCT FROM 'approved'
 OR reviewed.result_state->>'case_id' IS DISTINCT FROM request.case_id::text
 OR reviewed.result_state->'version' IS DISTINCT FROM
 to_jsonb(reviewed.version)
 OR reviewed.result_state->>'source_hash' IS DISTINCT FROM reviewed.source_hash
 OR reviewed.result_state_hash IS DISTINCT FROM
 correction_approval_hash(reviewed.result_state)
 OR correction_approval_chain(request.case_id,reviewed.version)
 IS DISTINCT FROM true
 OR receipt.result->>'intent_id' IS DISTINCT FROM authority->>'intent_id'
 OR receipt.result->>'approval_id' IS DISTINCT FROM authority->>'approval_id'
 OR NOT COALESCE(receipt.result @> reviewed.result_state,false)
 THEN RAISE EXCEPTION 'correction_review_authority_invalid' USING
 ERRCODE='23514'; END IF;
 SELECT * INTO payment FROM payments WHERE
 payment_id=(authority->>'payment_id')::uuid;
 SELECT * INTO capture FROM outbox_events WHERE
 event_id=(authority->>'capture_id')::uuid;
 SELECT * INTO invoice FROM outbox_events WHERE
 aggregate_id=request.order_id::text
   AND event_type='financial.capture_intent';
 SELECT count(*) INTO n FROM outbox_events WHERE
 aggregate_id=request.order_id::text
   AND event_type='financial.client_snapshot_requested';
 SELECT
 jsonb_agg(jsonb_build_array(paid_item_id,selection_minor,accompaniment_minor)
 ORDER BY ordinal) INTO components FROM order_items WHERE
 order_id=request.order_id;
 SELECT * INTO policy FROM financial_policy_versions WHERE
 version=ordered.financial_version;
 expected :=
 jsonb_build_object('order_id',request.order_id,'client_id',request.client_id,
'provider','yookassa_telegram','account',invoice.payload->>'account','currency','RUB',
'amount_minor',payment.captured_minor,'policy_version',ordered.financial_version,
 'quote_key',invoice.payload->>'quote_key','components',components);
 IF payment.payment_id IS NULL OR payment.order_id IS DISTINCT FROM
 request.order_id
 OR payment.status::text IS DISTINCT FROM 'paid' OR payment.currency IS
 DISTINCT FROM 'RUB'
 OR payment.provider IS DISTINCT FROM 'yookassa_telegram' OR
 payment.captured_minor IS NULL
 OR payment.captured_minor<>payment.amount*100 OR payment.paid_at IS NULL
 OR payment.financial_version IS DISTINCT FROM ordered.financial_version
 OR n<>1 OR capture.event_type IS DISTINCT FROM
 'financial.client_snapshot_requested'
 OR capture.aggregate_type IS DISTINCT FROM 'order'
 OR capture.aggregate_id IS DISTINCT FROM request.order_id::text
 OR capture.event_id=invoice.event_id
 OR capture.payload->>'payment_id' IS DISTINCT FROM payment.payment_id::text
 OR invoice.event_type IS DISTINCT FROM 'financial.capture_intent'
 OR invoice.aggregate_type IS DISTINCT FROM 'order'
 OR invoice.payload IS DISTINCT FROM expected
 OR NULLIF(trim(invoice.payload->>'account'),'') IS NULL
 OR NULLIF(trim(payment.external_id),'') IS NULL
 OR capture.payload->'capture' IS DISTINCT FROM expected||jsonb_build_object(
'external_id',payment.external_id,'telegram_payment_charge_id',capture.payload#>>'{capture,telegram_payment_charge_id}',
'captured_at',capture.payload#>>'{capture,captured_at}','captured_at_source','telegram.message.date')
 OR NULLIF(trim(capture.payload#>>'{capture,telegram_payment_charge_id}'),'')
 IS NULL
 OR (capture.payload#>>'{capture,captured_at}')::timestamptz IS DISTINCT FROM
 payment.paid_at
 OR payment.paid_at>clock_timestamp()
 OR policy.approved_by IS NULL OR policy.approved_at IS NULL
 OR policy.effective_from>ordered.created_at OR
 ordered.created_at>payment.paid_at
 OR policy.refund_window_seconds IS NULL OR policy.refund_window_seconds<=0
 OR NULLIF(policy.rules->>'terms_reference','') IS NULL
 OR NOT COALESCE(policy.rules->'allowed_clients' @>
 to_jsonb(ARRAY[request.client_id::text]),false)
 THEN RAISE EXCEPTION 'correction_approval_capture_invalid' USING
 ERRCODE='23514'; END IF;
 SELECT jsonb_agg(jsonb_build_array(paid_item_id,selection_minor) ORDER BY
 ordinal)
 INTO selected FROM order_items WHERE order_id=request.order_id;
 IF capture.payload->'selection_bases' IS DISTINCT FROM selected THEN
 RAISE EXCEPTION 'correction_approval_capture_invalid' USING ERRCODE='23514';
 END IF;
 IF jsonb_typeof(authority->'bundle') IS DISTINCT FROM 'array'
 OR jsonb_array_length(authority->'bundle') NOT BETWEEN 1 AND 200
 OR (SELECT sum((e->>'gross_minor')::bigint) FROM
jsonb_array_elements(authority->'bundle') e) IS DISTINCT FROM
 (authority->>'amount_minor')::bigint
 OR (SELECT count(DISTINCT element.val->>'paid_item_id') FROM
 jsonb_array_elements(authority->'bundle') element(val))
 <>jsonb_array_length(authority->'bundle')
 OR (SELECT count(DISTINCT element.val->>'allocation_key') FROM
 jsonb_array_elements(authority->'bundle') element(val))
 <>jsonb_array_length(authority->'bundle')
 OR (SELECT jsonb_agg(x ORDER BY x) FROM
 jsonb_array_elements_text(request.paid_item_ids) x)
 IS DISTINCT FROM (SELECT jsonb_agg(element.val->>'paid_item_id' ORDER BY
 element.val->>'paid_item_id')
 FROM jsonb_array_elements(authority->'bundle') element(val))
 THEN RAISE EXCEPTION 'correction_approval_bundle_invalid' USING
 ERRCODE='23514'; END IF;
 SELECT * INTO intake FROM order_intake_receipts WHERE
 order_id=request.order_id;
 FOR b IN SELECT val FROM jsonb_array_elements(authority->'bundle') val LOOP
 SELECT * INTO item FROM order_items WHERE
 paid_item_id=(b->>'paid_item_id')::uuid;
 SELECT * INTO allocation FROM payment_item_allocations WHERE
 allocation_key=b->>'allocation_key';
 due_hash := correction_approval_hash(jsonb_build_object(
'receipt',correction_approval_row(to_jsonb(intake),'order_intake_receipts'::regclass),
 'quote',item.quote_payload,'due',to_char(item.selection_due_at AT TIME ZONE
 'UTC',
 'YYYY-MM-DD"T"HH24:MI:SS.US')||'+00:00'));
 IF item.order_id IS DISTINCT FROM request.order_id OR item.currency IS
 DISTINCT FROM 'RUB'
 OR item.selection_minor IS DISTINCT FROM
COALESCE((policy.rules->>'selection_minor')::bigint,50000) OR
item.accompaniment_minor NOT
 IN (0,COALESCE((policy.rules->>'accompaniment_minor')::bigint,120000))
 OR item.policy_version IS DISTINCT FROM ordered.financial_version
 OR item.quote_key IS DISTINCT FROM invoice.payload->>'quote_key'
 OR item.quote_payload->>'client_id' IS DISTINCT FROM request.client_id::text
 OR item.quote_payload->>'terms_reference' IS DISTINCT FROM
 policy.rules->>'terms_reference'
 OR item.captured_at IS DISTINCT FROM payment.paid_at OR
 item.selection_due_at<=payment.paid_at
 OR (authority->>'recorded_at')::timestamptz<=item.selection_due_at
 OR item.selection_state NOT IN ('paid','delivered','refunded','cancelled')
 OR intake.client_id IS DISTINCT FROM request.client_id
 OR intake.result->>'selection_due_at' IS DISTINCT FROM
 item.quote_payload->>'selection_due_at'
 OR (intake.result->>'selection_due_at')::timestamptz IS DISTINCT FROM
 item.selection_due_at
 OR intake.result->>'terms_reference' IS DISTINCT FROM
 item.quote_payload->>'terms_reference'
 OR intake.result->>'policy_version' IS DISTINCT FROM item.policy_version
 OR jsonb_array_length(intake.result->'items') IS DISTINCT FROM
ordered.bloggers_needed
 OR allocation.payment_id IS DISTINCT FROM payment.payment_id
 OR allocation.order_id IS DISTINCT FROM request.order_id OR
 allocation.paid_item_id IS DISTINCT FROM item.paid_item_id
 OR allocation.component IS DISTINCT FROM 'selection' OR
 allocation.amount_minor IS DISTINCT FROM item.selection_minor
 OR allocation.currency IS DISTINCT FROM 'RUB'
 OR b->>'payment_id' IS DISTINCT FROM payment.payment_id::text
 OR b->'gross_minor' IS DISTINCT FROM to_jsonb(item.selection_minor) OR
b->>'currency' IS
 DISTINCT FROM 'RUB'
 OR (b->>'selection_due_at')::timestamptz IS DISTINCT FROM
 item.selection_due_at
 OR b->>'due_evidence_hash' IS DISTINCT FROM due_hash
 OR b->'assignment_ids' IS DISTINCT FROM '[]'::jsonb OR
 b->'accepted_delivery_ids' IS DISTINCT FROM '[]'::jsonb
 OR EXISTS (SELECT 1 FROM item_assignments WHERE
 paid_item_id=item.paid_item_id)
 OR EXISTS (SELECT 1 FROM paid_selection_accepted_deliveries WHERE
 paid_item_id=item.paid_item_id)
 OR EXISTS (SELECT 1 FROM financial_obligations WHERE
 paid_item_id=item.paid_item_id AND kind<>'client_referral')
 THEN RAISE EXCEPTION 'correction_approval_component_invalid' USING
 ERRCODE='23514'; END IF;
 normalized_bundle := normalized_bundle ||
 jsonb_build_array(b||jsonb_build_object('selection_due_at',
 to_char(item.selection_due_at AT TIME ZONE
 'UTC','YYYY-MM-DD"T"HH24:MI:SS.US')||'+00:00'));
 END LOOP;
 SELECT
COALESCE(jsonb_agg(correction_approval_row(to_jsonb(g),'financial_obligations'::regclass)
 ORDER BY paid_item_id),'[]') INTO actual_grounds FROM financial_obligations g
 WHERE paid_item_id::text IN (SELECT
 jsonb_array_elements_text(request.paid_item_ids));
 SELECT jsonb_agg(correction_approval_row(to_jsonb(i),'order_items'::regclass)
 ORDER BY ordinal)
 INTO selected FROM order_items i WHERE paid_item_id::text IN (SELECT
 jsonb_array_elements_text(request.paid_item_ids));
 source_hash := correction_approval_hash(jsonb_build_object(
'capture_source_hash',correction_approval_hash(jsonb_build_object('event_id',capture.event_id,
'event_type',capture.event_type,'aggregate_id',capture.aggregate_id,'aggregate_type',capture.aggregate_type,'payload',capture.payload)),
'selected_items',selected,'bundle',jsonb_build_object('components',normalized_bundle),
 'assignments','[]'::jsonb,'deliveries','[]'::jsonb,'grounds',actual_grounds,
'intake',jsonb_build_array(correction_approval_row(to_jsonb(intake),'order_intake_receipts'::regclass))));
 IF authority->>'source_hash' IS DISTINCT FROM source_hash THEN
 RAISE EXCEPTION 'correction_approval_source_seal_invalid' USING
 ERRCODE='23514'; END IF;
 IF is_new THEN
 expected :=
 jsonb_build_object('invoice',jsonb_build_object('event_id',invoice.event_id,
'event_type',invoice.event_type,'aggregate_id',invoice.aggregate_id,'aggregate_type',invoice.aggregate_type,'payload',invoice.payload),
'payment',jsonb_build_object('payment_id',payment.payment_id,'order_id',payment.order_id,
'provider',payment.provider,'status',payment.status,'external_id',payment.external_id,'currency',payment.currency,
'captured_minor',payment.captured_minor,'paid_at',authority#>>'{source_capsule,payment,paid_at}'),
 'invoice_intent_id',invoice.event_id,'capture_id',capture.event_id,
 'captured_at',authority#>>'{source_capsule,captured_at}',
'quote_key',invoice.payload->>'quote_key','terms_reference',policy.rules->>'terms_reference',
 'ground_ids',COALESCE((SELECT jsonb_agg(id ORDER BY id)
 FROM financial_obligations WHERE order_id=request.order_id),'[]'),
 'selected_paid_item_ids',request.paid_item_ids);
 IF authority->'source_capsule' IS DISTINCT FROM expected
 OR (authority#>>'{source_capsule,payment,paid_at}')::timestamptz IS DISTINCT
 FROM payment.paid_at
 OR (authority#>>'{source_capsule,captured_at}')::timestamptz IS DISTINCT FROM
 payment.paid_at THEN
 RAISE EXCEPTION 'correction_approval_capsule_invalid' USING ERRCODE='23514';
 END IF;
 END IF;
END $$;

CREATE OR REPLACE FUNCTION correction_match_capsule(selected_match uuid,
 require_current boolean DEFAULT true) RETURNS TABLE(
 intent_id uuid, case_id uuid, command_id uuid, request_id uuid, capture_id
 uuid,
 payment_id uuid, source_hash varchar, bundle jsonb, amount_minor bigint,
 currency varchar, review_version bigint, recorded_at timestamptz)
LANGUAGE plpgsql AS $$
DECLARE m record; linked record; a jsonb; c record; e record; o record;
 p record; original record; original_command record; selected_invoice uuid;
 latest bigint; n integer;
BEGIN
 SELECT * INTO m FROM financial_refund_matches WHERE match_id=selected_match;
 SELECT * INTO linked FROM financial_refund_match_approvals WHERE
 match_id=selected_match;
 IF m.match_id IS NULL THEN RAISE EXCEPTION
 'correction_match_authority_invalid' USING ERRCODE='23514'; END IF;
 IF linked.approval_id IS NOT NULL THEN
 SELECT to_jsonb(x) INTO a FROM financial_refund_intent_approvals x WHERE
 x.approval_id=linked.approval_id;
 ELSE SELECT to_jsonb(x) INTO a FROM financial_refund_intents x WHERE
 x.intent_id=m.intent_id;
 END IF;
 SELECT * INTO c FROM financial_correction_commands WHERE
 financial_correction_commands.command_id=m.command_id;
 SELECT * INTO e FROM financial_correction_events WHERE
 financial_correction_events.command_id=m.command_id
 AND source_id=m.match_id;
 SELECT count(*) INTO n FROM financial_correction_events WHERE
 financial_correction_events.command_id=m.command_id
 AND source_id=m.match_id;
 IF c.action IS DISTINCT FROM 'MatchSelectionRefund' OR n<>1
 OR c.result->>'match_id' IS DISTINCT FROM m.match_id::text
 OR c.result->>'approval_id' IS DISTINCT FROM linked.approval_id::text
 OR e.case_id IS DISTINCT FROM m.case_id OR e.actor_id IS DISTINCT FROM
 c.actor_id
 OR e.source_hash IS DISTINCT FROM m.source_hash OR e.recorded_at IS DISTINCT
 FROM m.recorded_at
 OR e.result_state->>'match_status' IS DISTINCT FROM 'matched'
 OR e.result_state->>'application_status' IS DISTINCT FROM
 'awaiting_assessment'
 OR e.result_state->>'case_id' IS DISTINCT FROM m.case_id::text
 OR e.result_state->'version' IS DISTINCT FROM to_jsonb(e.version)
 OR e.result_state->>'source_hash' IS DISTINCT FROM m.source_hash
 OR e.result_state_hash IS DISTINCT FROM
 correction_approval_hash(e.result_state)
 OR correction_approval_chain(m.case_id,e.version) IS DISTINCT FROM true
 OR NOT COALESCE(c.result @> e.result_state,false)
 OR a IS NULL OR a->>'intent_id' IS DISTINCT FROM m.intent_id::text
 OR a->>'case_id' IS DISTINCT FROM m.case_id::text
 OR a->>'capture_id' IS DISTINCT FROM m.capture_id::text
 OR a->>'payment_id' IS DISTINCT FROM m.payment_id::text
 OR a->>'source_hash' IS DISTINCT FROM m.source_hash
 OR a->'bundle' IS DISTINCT FROM m.bundle
 OR a->'amount_minor' IS DISTINCT FROM to_jsonb(m.amount_minor)
 OR a->>'currency' IS DISTINCT FROM m.currency
 OR a->'review_version' IS DISTINCT FROM to_jsonb(m.review_version)
 OR (linked.approval_id IS NULL AND (a->>'request_id' IS NULL OR
 a->>'review_version' IS NULL))
 THEN RAISE EXCEPTION 'correction_match_authority_invalid' USING
 ERRCODE='23514'; END IF;
 IF NOT EXISTS (SELECT 1 FROM financial_correction_requests r WHERE
 r.request_id=(a->>'request_id')::uuid AND r.case_id=m.case_id AND
 r.order_id=m.order_id) THEN
 RAISE EXCEPTION 'correction_match_authority_invalid' USING ERRCODE='23514';
 END IF;
 PERFORM correction_validate_authority(a);
 SELECT max(ev.version) INTO latest FROM financial_correction_events ev
 JOIN financial_correction_commands cmd ON cmd.command_id=ev.command_id
 WHERE ev.case_id=m.case_id AND cmd.action='ReviewSelectionRefund'
 AND (require_current OR ev.version<e.version);
 IF require_current AND correction_approval_chain(m.case_id,
 (SELECT max(ev.version) FROM financial_correction_events ev
 WHERE ev.case_id=m.case_id)) IS DISTINCT FROM true THEN
 RAISE EXCEPTION 'correction_match_authority_invalid' USING ERRCODE='23514';
 END IF;
 IF latest IS DISTINCT FROM m.review_version THEN
 RAISE EXCEPTION 'correction_match_review_ineffective' USING ERRCODE='23514';
 END IF;
 SELECT * INTO o FROM financial_refund_observations WHERE
 observation_id=m.observation_id;
 SELECT * INTO c FROM financial_correction_commands WHERE
 financial_correction_commands.command_id=o.command_id;
 SELECT event_id INTO selected_invoice FROM outbox_events WHERE
 aggregate_id=m.order_id::text
 AND event_type='financial.capture_intent';
 IF o.intent_id IS DISTINCT FROM m.intent_id OR o.case_id IS DISTINCT FROM
 m.case_id
 OR o.amount_minor IS DISTINCT FROM m.amount_minor OR o.currency IS DISTINCT
 FROM 'RUB'
 OR o.reported_component IS DISTINCT FROM 'selection'
 OR o.known_order_id IS NOT NULL AND o.known_order_id<>m.order_id
 OR o.known_capture_intent_id IS NOT NULL AND
 o.known_capture_intent_id<>selected_invoice
 OR o.original_payment_reference IS DISTINCT FROM (SELECT external_id FROM
 payments WHERE payments.payment_id=m.payment_id)
 OR c.action IS DISTINCT FROM 'RecordManualRefundObservation'
 OR c.result->>'observation_id' IS DISTINCT FROM o.observation_id::text
 OR c.result->>'intent_id' IS DISTINCT FROM o.intent_id::text
 OR c.result->>'case_id' IS DISTINCT FROM o.case_id::text THEN
 RAISE EXCEPTION 'correction_match_observation_invalid' USING ERRCODE='23514';
 END IF;
 SELECT count(*) INTO n FROM financial_physical_proof_claims q
 WHERE q.account=o.bank_account_label AND q.reference=o.bank_reference AND
 q.direction='outgoing';
 IF n<>1 THEN RAISE EXCEPTION 'correction_match_proof_invalid' USING
 ERRCODE='23514'; END IF;
 SELECT * INTO p FROM financial_physical_proof_claims q
 WHERE q.account=o.bank_account_label AND q.reference=o.bank_reference AND
 q.direction='outgoing';
 SELECT * INTO original FROM financial_refund_observations WHERE
 observation_id=p.observation_id;
 SELECT * INTO original_command FROM financial_correction_commands WHERE
 financial_correction_commands.command_id=p.command_id;
 IF p.producer IS DISTINCT FROM 'refund' OR p.intent_id IS DISTINCT FROM
 m.intent_id
 OR p.key_hash IS DISTINCT FROM encode(sha256(convert_to(
 correction_approval_json(jsonb_build_array(p.source,p.account,p.direction,
 p.reference)),'UTF8')),'hex')
 OR original.intent_id IS DISTINCT FROM m.intent_id OR original.case_id IS
 DISTINCT FROM m.case_id
 OR original.command_id IS DISTINCT FROM p.command_id
 OR original.bank_account_label IS DISTINCT FROM p.account OR
 original.bank_reference IS DISTINCT FROM p.reference
 OR original_command.action IS DISTINCT FROM 'RecordManualRefundObservation'
 OR original_command.result->>'observation_id' IS DISTINCT FROM
 p.observation_id::text
 OR original_command.result->>'intent_id' IS DISTINCT FROM m.intent_id::text
 OR original_command.result->>'case_id' IS DISTINCT FROM m.case_id::text THEN
 RAISE EXCEPTION 'correction_match_proof_invalid' USING ERRCODE='23514'; END
 IF;
 RETURN QUERY SELECT
 (a->>'intent_id')::uuid,(a->>'case_id')::uuid,(a->>'command_id')::uuid,
 (a->>'request_id')::uuid,(a->>'capture_id')::uuid,(a->>'payment_id')::uuid,
 (a->>'source_hash')::varchar,a->'bundle',(a->>'amount_minor')::bigint,
(a->>'currency')::varchar,(a->>'review_version')::bigint,(a->>'recorded_at')::timestamptz;
END $$;

CREATE OR REPLACE FUNCTION correction_check_approval() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
 IF TG_TABLE_NAME='financial_refund_intent_approvals' THEN
 PERFORM correction_validate_authority(to_jsonb(NEW));
 IF NOT EXISTS (SELECT 1 FROM financial_correction_commands c JOIN users u ON
 u.user_id=c.actor_id
 WHERE c.command_id=NEW.command_id AND u.status::text='active' AND u.admin)
 THEN
 RAISE EXCEPTION 'correction_approval_admin_required' USING ERRCODE='23514';
 END IF;
 ELSE PERFORM correction_match_capsule(NEW.match_id,false);
 END IF;
 RETURN NEW;
END $$;
"""

# The historical builder remains byte-frozen. Only the authority lookup changes;
# All original component, capacity, pending, issuance and wallet checks stay.
FINAL_APPLICATION_SQL = CURRENT_GUARD_SQL.replace(
    "SELECT * INTO intent FROM financial_refund_intents WHERE\n"
    "intent_id=app.intent_id;",
    "SELECT * INTO intent FROM correction_match_capsule(app.match_id);",
)


def correction_approval_trigger_sql(tables, *, install_match=True):
    statements = [APPROVAL_SQL, FINAL_APPLICATION_SQL]
    for table in tables.values():
        statements.extend(
            [
                "DROP TRIGGER IF EXISTS correction_fact_immutable "
                f"ON {table.name};",
                "CREATE TRIGGER correction_fact_immutable BEFORE UPDATE "
                "OR DELETE OR TRUNCATE "
                f"ON {table.name} FOR EACH STATEMENT "
                "EXECUTE FUNCTION correction_deny_mutation();",
                "DROP TRIGGER IF EXISTS correction_approval_guard "
                f"ON {table.name};",
                "CREATE CONSTRAINT TRIGGER correction_approval_guard "
                "AFTER INSERT "
                f"ON {table.name} DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
                "EXECUTE FUNCTION correction_check_approval();",
            ]
        )
    if install_match:
        statements.extend(
            [
                "DROP TRIGGER IF EXISTS correction_approval_guard "
                "ON financial_refund_matches;",
                "CREATE CONSTRAINT TRIGGER correction_approval_guard "
                "AFTER INSERT ON financial_refund_matches "
                "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
                "EXECUTE FUNCTION correction_check_approval();",
            ]
        )
    return "\n".join(statements)


def correction_approval_pending_sql(table):
    """Partial metadata must refuse writes until every source guard is ready."""
    immutable = CURRENT_GUARD_SQL.split(
        "CREATE OR REPLACE FUNCTION correction_check_application()", 1
    )[0]
    return (
        immutable
        + f"""
CREATE OR REPLACE FUNCTION correction_check_approval() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
 RAISE EXCEPTION 'correction_approval_schema_unavailable' USING ERRCODE='23514';
END $$;
CREATE TRIGGER correction_fact_immutable BEFORE UPDATE OR DELETE OR TRUNCATE
ON {table.name} FOR EACH STATEMENT EXECUTE FUNCTION correction_deny_mutation();
CREATE TRIGGER correction_approval_guard BEFORE INSERT ON {table.name}
FOR EACH ROW EXECUTE FUNCTION correction_check_approval();
"""
    )
