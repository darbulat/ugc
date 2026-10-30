"""Frozen tariff and quantity invariants; historical policies retain 500/1200
RUB.

Downgrade fails atomically if newer facts cannot satisfy the old tariff/count
constraints. No historical amount, quote payload, or receipt hash is rewritten.
"""

import sqlalchemy as sa
from alembic import op

revision = "0120_variable_tariff"
down_revision = "0119_accompaniment_prior"
branch_labels = None
depends_on = None

UPGRADE_SQL = r"""
CREATE OR REPLACE FUNCTION correction_zero_assessment_valid(
 p_potential uuid, p_capture uuid, p_payment uuid, p_order uuid,
 p_item uuid, p_client uuid, p_gross bigint
) RETURNS boolean LANGUAGE plpgsql AS $$
DECLARE potential record; capture record; item record; fact jsonb;
 details jsonb; captured timestamptz; registered timestamptz;
 recipient uuid; expected_rate integer; override_count integer;
 selected_override uuid; basis_key text;
BEGIN
 SELECT * INTO potential FROM financial_audit_events WHERE id=p_potential;
 IF NOT FOUND THEN RETURN false; END IF;
 SELECT * INTO capture FROM outbox_events WHERE event_id=p_capture;
 IF NOT FOUND THEN RETURN false; END IF;
 SELECT * INTO item FROM order_items WHERE paid_item_id=p_item;
 IF NOT FOUND OR item.order_id IS DISTINCT FROM p_order
 OR item.selection_minor IS DISTINCT FROM p_gross THEN RETURN false; END IF;
 fact:=capture.payload#>'{attribution_history,fact}';
 details:=potential.details;
 captured:=(capture.payload#>>'{capture,captured_at}')::timestamptz;
 registered:=(fact->>'registered_at')::timestamptz;
 recipient:=(fact->>'referrer_user_id')::uuid;
 basis_key:='client-selection:'||p_payment::text||':'||p_item::text;
 IF captured IS NULL OR registered IS NULL OR recipient IS NULL
 OR recipient=p_client OR registered>captured
 OR capture.event_type IS DISTINCT FROM 'financial.client_snapshot_requested'
 OR capture.aggregate_id IS DISTINCT FROM p_order::text
 OR capture.payload->>'payment_id' IS DISTINCT FROM p_payment::text
 OR capture.payload#>>'{capture,client_id}' IS DISTINCT FROM p_client::text
 OR capture.payload->>'client_referrer_id' IS DISTINCT FROM recipient::text
 OR (capture.payload->>'client_registered_at')::timestamptz
    IS DISTINCT FROM registered
 OR capture.payload#>>'{attribution_history,status}' IS DISTINCT FROM 'assessed'
 OR fact->>'referred_user_id' IS DISTINCT FROM p_client::text
 OR (fact->>'as_of')::timestamptz IS DISTINCT FROM captured
 OR fact->>'reason' IS NOT NULL
 OR NULLIF(fact->>'coverage_version','') IS NULL
 OR fact->>'binding_created_at' IS NULL
 OR fact->>'binding_effective_at' IS NULL
 OR (fact->>'binding_created_at')::timestamptz>captured
 OR (fact->>'binding_effective_at')::timestamptz>captured
 OR fact->>'covered_from' IS NULL OR fact->>'observed_through' IS NULL
 OR (fact->>'covered_from')::timestamptz>captured
 OR (fact->>'observed_through')::timestamptz<captured
 THEN RETURN false; END IF;
 IF potential.action IS DISTINCT FROM 'potential_basis'
 OR potential.reason IS DISTINCT FROM 'rounded_commission_zero'
 OR potential.operation_key IS DISTINCT FROM 'potential:'||basis_key
 OR potential.scope IS DISTINCT FROM 'paid_item:'||p_item::text
 OR potential.effective_at IS DISTINCT FROM captured
 OR potential.recorded_at<captured
 OR potential.actor_id IS DISTINCT FROM p_client
 OR potential.actor_kind IS DISTINCT FROM 'user'
 OR potential.system_actor IS NOT NULL
 OR potential.obligation_id IS NOT NULL OR potential.movement_id IS NOT NULL
 OR details->>'business_key' IS DISTINCT FROM basis_key
 OR details->>'kind' IS DISTINCT FROM 'client_referral'
 OR details->>'recipient_id' IS DISTINCT FROM recipient::text
 OR details->>'referred_user_id' IS DISTINCT FROM p_client::text
 OR details->>'actor_id' IS DISTINCT FROM p_client::text
 OR details->>'actor_kind' IS DISTINCT FROM 'user'
 OR details->>'system_actor' IS NOT NULL
 OR details->>'paid_item_id' IS DISTINCT FROM p_item::text
 OR details->>'payment_id' IS DISTINCT FROM p_payment::text
 OR details->>'order_id' IS DISTINCT FROM p_order::text
 OR details->>'policy_version' IS DISTINCT FROM item.policy_version
 OR details->>'currency' IS DISTINCT FROM 'RUB'
 OR details->>'event_id' IS DISTINCT FROM p_capture::text
 OR details->>'reason' IS DISTINCT FROM 'confirmed_selection_capture'
 OR details->>'assignment_id' IS NOT NULL
 OR details->>'verified_count' IS NOT NULL
 OR details->>'available_at' IS NOT NULL
 OR (details->>'base_minor')::bigint IS DISTINCT FROM p_gross
 OR (details->>'snapshot_at')::timestamptz IS DISTINCT FROM captured
 OR (details->>'registered_at')::timestamptz IS DISTINCT FROM registered
 THEN RETURN false; END IF;
 SELECT count(*) INTO override_count FROM financial_rate_overrides r
 WHERE r.recipient_id=recipient AND r.side='client'
 AND r.policy_version=item.policy_version AND r.approved_at<=captured
 AND r.effective_from<=captured AND captured<r.effective_until
 AND NOT EXISTS (SELECT 1 FROM financial_override_events e
   WHERE e.override_id=r.override_id
   AND e.event_type IN ('revoked','superseded')
   AND e.effective_at<=captured);
 IF override_count>1 THEN RETURN false;
 ELSIF override_count=1 THEN
   SELECT r.override_id,r.rate_bps INTO selected_override,expected_rate
   FROM financial_rate_overrides r WHERE r.recipient_id=recipient
   AND r.side='client' AND r.policy_version=item.policy_version
   AND r.approved_at<=captured AND r.effective_from<=captured
   AND captured<r.effective_until
   AND NOT EXISTS (SELECT 1 FROM financial_override_events e
     WHERE e.override_id=r.override_id
   AND e.event_type IN ('revoked','superseded')
     AND e.effective_at<=captured);
   IF details->>'rate_source' IS DISTINCT FROM 'override'
   OR details->>'override_id' IS DISTINCT FROM selected_override::text
   THEN RETURN false; END IF;
 ELSE
   expected_rate:=CASE WHEN captured>=
     ((registered AT TIME ZONE 'UTC')+interval '1 year') AT TIME ZONE 'UTC'
     THEN 300 ELSE 1000 END;
   IF details->>'rate_source' IS DISTINCT FROM 'standard'
   OR details->>'override_id' IS NOT NULL THEN RETURN false; END IF;
 END IF;
 RETURN (details->>'rate_bps')::integer IS NOT DISTINCT FROM expected_rate
 AND p_gross>0 AND floor((p_gross::numeric*expected_rate+5000)/10000)=0
 AND NOT EXISTS (SELECT 1 FROM financial_obligations
 WHERE business_key=basis_key);
END $$;
ALTER TABLE financial_refund_liability_assessments
DROP CONSTRAINT ck_correction_liability;
ALTER TABLE financial_refund_liability_assessments
ADD CONSTRAINT ck_correction_liability CHECK (
status IN ('pending_cancelled','covered_absence','covered_zero') AND
 target_minor>=0 AND already_cancelled_minor>=0 AND
 delta_minor=target_minor-already_cancelled_minor AND delta_minor>=0 AND
 (frozen_rate_bps IS NULL OR frozen_rate_bps BETWEEN 0 AND 10000));

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
 SELECT * INTO intent FROM correction_match_capsule(app.match_id);
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
   ELSIF liability.status='covered_zero' THEN
     IF correction_zero_assessment_valid(liability.potential_id,
       app.capture_id,app.payment_id,app.order_id,component.paid_item_id,
       request.client_id,component.gross_minor) IS NOT TRUE
       OR liability.obligation_id IS NOT NULL
       OR liability.snapshot_id IS NOT NULL
       OR liability.issuance_entry_id IS NOT NULL
       OR liability.movement_id IS NOT NULL
       OR liability.frozen_rate_bps IS NOT NULL
       OR liability.override_id IS NOT NULL
       OR liability.target_minor<>0 OR liability.already_cancelled_minor<>0
       OR liability.delta_minor<>0
     THEN RAISE EXCEPTION 'correction_zero_assessment_unavailable'; END IF;
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
ALTER TABLE financial_accompaniment_refund_applications DROP CONSTRAINT
ck_accompaniment_application_values;
ALTER TABLE financial_accompaniment_refund_applications ADD CONSTRAINT
ck_accompaniment_application_values CHECK (customer_target_minor>0 AND
customer_delta_minor>0 AND customer_delta_minor<=customer_target_minor AND
manager_target_minor BETWEEN 0 AND 60000 AND manager_delta_minor BETWEEN 0 AND
manager_target_minor AND ((work_version=0 AND assignment_id IS NULL AND stage
IS NULL AND manager_target_minor=0) OR (work_version>0 AND assignment_id IS
NOT NULL AND stage IS NOT NULL)));
ALTER TABLE financial_accompaniment_management_reviews DROP CONSTRAINT
ck_accompaniment_management_review;
ALTER TABLE financial_accompaniment_management_reviews ADD CONSTRAINT
ck_accompaniment_management_review CHECK (decision IN ('continue','cancel')
AND customer_net_minor>=0 AND work_version>0);
ALTER TABLE financial_refund_intent_approvals DROP CONSTRAINT
ck_correction_approval_capsule;
ALTER TABLE financial_refund_intent_approvals ADD CONSTRAINT
ck_correction_approval_capsule CHECK (source_hash ~ '^[0-9a-f]{64}$' AND
currency='RUB' AND amount_minor>0 AND review_version>0 AND
jsonb_typeof(source_capsule)='object' AND jsonb_typeof(bundle)='array' AND
jsonb_array_length(bundle) BETWEEN 1 AND 200);
ALTER TABLE financial_correction_requests DROP CONSTRAINT
ck_correction_request_items;
ALTER TABLE financial_correction_requests ADD CONSTRAINT
ck_correction_request_items CHECK (jsonb_typeof(paid_item_ids)='array' AND
jsonb_array_length(paid_item_ids) BETWEEN 1 AND 200);
ALTER TABLE financial_refund_matches DROP CONSTRAINT ck_correction_match;
ALTER TABLE financial_refund_matches ADD CONSTRAINT ck_correction_match CHECK
(amount_minor>0 AND currency='RUB' AND review_version>0 AND
jsonb_typeof(bundle)='array' AND jsonb_array_length(bundle) BETWEEN 1 AND
200);
ALTER TABLE financial_refund_component_applications DROP CONSTRAINT
ck_correction_component;
ALTER TABLE financial_refund_component_applications ADD CONSTRAINT
ck_correction_component CHECK (component='selection' AND currency='RUB' AND
gross_minor>0 AND prior_refund_minor>=0 AND
new_refund_minor=prior_refund_minor+refund_minor AND
new_refund_minor<=gross_minor AND refund_minor=gross_minor);
ALTER TABLE financial_refund_original_assessments DROP CONSTRAINT
ck_refund_original_grounds;
ALTER TABLE financial_refund_original_assessments ADD CONSTRAINT
ck_refund_original_grounds CHECK (jsonb_typeof(new_ground_ids)='array' AND
jsonb_array_length(new_ground_ids) BETWEEN 1 AND 200);
ALTER TABLE paid_selection_accepted_deliveries DROP CONSTRAINT
ck_selection_accepted_value;
ALTER TABLE paid_selection_accepted_deliveries ADD CONSTRAINT
ck_selection_accepted_value CHECK (currency='RUB' AND amount_minor>0 AND
length(trim(instagram_user_id))>0 AND length(trim(provider_reference))>0);
CREATE OR REPLACE FUNCTION intake_validate_source() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE owner uuid; expected_count integer; actual_count integer;
matched_count integer;
BEGIN
    SELECT advertiser_id, bloggers_needed INTO owner, expected_count FROM orders
        WHERE order_id=NEW.order_id AND created_at=NEW.requested_at;
    IF owner IS DISTINCT FROM NEW.client_id
       OR NEW.result->>'order_id' IS DISTINCT FROM NEW.order_id::text
       OR NEW.result->>'request_id' IS DISTINCT FROM NEW.request_id::text
       OR NEW.result->>'honorarium_payment' IS DISTINCT FROM 'paid_direct' THEN
        RAISE EXCEPTION 'intake_source_mismatch';
    END IF;
    SELECT count(*) INTO actual_count FROM order_items
        WHERE order_id=NEW.order_id;
    SELECT count(DISTINCT actual.paid_item_id) INTO matched_count
        FROM jsonb_array_elements(NEW.result->'items') requested
        JOIN order_items actual
          ON actual.paid_item_id=(requested->>'paid_item_id')::uuid
         AND actual.order_id=NEW.order_id
         AND actual.ordinal=(requested->>'ordinal')::integer
         AND actual.selection_minor=COALESCE((SELECT
(rules->>'selection_minor')::bigint FROM financial_policy_versions WHERE
version=actual.policy_version),50000)
         AND actual.selection_minor=(requested->>'selection_minor')::bigint
         AND actual.accompaniment_minor IN (0,COALESCE((SELECT
(rules->>'accompaniment_minor')::bigint FROM financial_policy_versions WHERE
version=actual.policy_version),120000))
         AND actual.accompaniment_minor=
             (requested->>'accompaniment_minor')::bigint
         AND actual.currency=NEW.result->>'currency'
         AND actual.policy_version=NEW.result->>'policy_version'
         AND actual.selection_due_at=
             (NEW.result->>'selection_due_at')::timestamptz
         AND actual.quote_payload->>'terms_reference'=
             NEW.result->>'terms_reference';
    IF expected_count NOT BETWEEN 10 AND 200 OR actual_count <> expected_count
       OR matched_count <> expected_count
       OR jsonb_array_length(NEW.result->'items') <> expected_count
       OR EXISTS (SELECT 1 FROM order_items WHERE order_id=NEW.order_id AND
ordinal NOT BETWEEN 1 AND expected_count) THEN
        RAISE EXCEPTION 'intake_quote_mismatch';
    END IF;
    RETURN NEW;
END $$;
CREATE OR REPLACE FUNCTION accompaniment_validate_lead() RETURNS trigger
LANGUAGE plpgsql AS $$ DECLARE receipt record; selected jsonb;
BEGIN
    SELECT * INTO receipt FROM order_intake_receipts
        WHERE request_id=NEW.request_id;
    SELECT jsonb_agg((item->>'ordinal')::integer
        ORDER BY (item->>'ordinal')::integer) INTO selected
        FROM jsonb_array_elements(receipt.result->'items') item
        WHERE (item->>'accompaniment_minor')::bigint>0;
    IF receipt.order_id IS DISTINCT FROM NEW.order_id
       OR receipt.client_id IS DISTINCT FROM NEW.client_id
       OR receipt.requested_at IS DISTINCT FROM NEW.requested_at
       OR receipt.result->>'lead_id' IS DISTINCT FROM NEW.lead_id::text
       OR selected IS NULL OR selected IS DISTINCT FROM NEW.selected_ordinals
       OR length(trim(NEW.contact_reference))=0 THEN
        RAISE EXCEPTION 'accompaniment_lead_source_mismatch';
    END IF;
    RETURN NEW;
END $$;
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
 jsonb_array_elements_text(request.paid_item_ids)) AND
correction_original_ground_visible(id,request.case_id,authority->>'source_hash');
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
 FROM financial_obligations WHERE order_id=request.order_id AND
correction_original_ground_visible(id,request.case_id,authority->>'source_hash')),'[]'),
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

CREATE OR REPLACE FUNCTION financial_policy_tariff_guard() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
 IF (NEW.rules ? 'selection_minor') <> (NEW.rules ? 'accompaniment_minor')
 OR (NEW.rules ? 'selection_minor' AND (
   jsonb_typeof(NEW.rules->'selection_minor') IS DISTINCT FROM 'number'
   OR jsonb_typeof(NEW.rules->'accompaniment_minor') IS DISTINCT FROM 'number'
   OR NEW.rules->>'selection_minor' !~ '^[0-9]+$'
   OR NEW.rules->>'accompaniment_minor' !~ '^[0-9]+$'
   OR (NEW.rules->>'selection_minor')::numeric NOT BETWEEN 1 AND
49999999
   OR (NEW.rules->>'accompaniment_minor')::numeric NOT BETWEEN 60000 AND
49999999
   OR ((NEW.rules->>'selection_minor')::numeric +
       (NEW.rules->>'accompaniment_minor')::numeric)*200 > 9999999999
 )) THEN
  RAISE EXCEPTION 'invalid_policy_tariff' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER financial_policy_tariff_source BEFORE INSERT ON
financial_policy_versions
FOR EACH ROW EXECUTE FUNCTION financial_policy_tariff_guard();

CREATE OR REPLACE FUNCTION financial_item_tariff_guard() RETURNS trigger
LANGUAGE plpgsql AS $$ DECLARE policy record; BEGIN
 SELECT * INTO policy FROM financial_policy_versions WHERE
version=NEW.policy_version;
 IF policy.version IS NULL
 OR NEW.selection_minor IS DISTINCT FROM
COALESCE((policy.rules->>'selection_minor')::bigint,50000)
 OR NEW.accompaniment_minor NOT IN
(0,COALESCE((policy.rules->>'accompaniment_minor')::bigint,120000)) THEN
  RAISE EXCEPTION 'item_policy_tariff_mismatch' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER financial_item_tariff_source BEFORE INSERT OR UPDATE ON
order_items
FOR EACH ROW EXECUTE FUNCTION financial_item_tariff_guard();

CREATE OR REPLACE FUNCTION financial_delivery_tariff_guard() RETURNS trigger
LANGUAGE plpgsql AS $$ DECLARE item record; allocation record; BEGIN
 SELECT * INTO item FROM order_items WHERE paid_item_id=NEW.paid_item_id;
 SELECT * INTO allocation FROM payment_item_allocations WHERE
allocation_key=NEW.allocation_key;
 IF item.paid_item_id IS NULL OR allocation.allocation_key IS NULL
 OR NEW.order_id IS DISTINCT FROM item.order_id
 OR NEW.policy_version IS DISTINCT FROM item.policy_version
 OR NEW.currency IS DISTINCT FROM item.currency
 OR allocation.order_id IS DISTINCT FROM NEW.order_id
 OR allocation.paid_item_id IS DISTINCT FROM NEW.paid_item_id
 OR allocation.payment_id IS DISTINCT FROM NEW.payment_id
 OR allocation.component IS DISTINCT FROM 'selection'
 OR allocation.currency IS DISTINCT FROM NEW.currency
 OR NEW.amount_minor IS DISTINCT FROM item.selection_minor
 OR NEW.amount_minor IS DISTINCT FROM allocation.amount_minor THEN
  RAISE EXCEPTION 'delivery_allocation_tariff_mismatch' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER financial_delivery_tariff_source BEFORE INSERT ON
paid_selection_accepted_deliveries
FOR EACH ROW EXECUTE FUNCTION financial_delivery_tariff_guard();

"""

# Freeze the preflight here too: earlier migrations must not import runtime SQL.
# Locks serialize all inspected facts against concurrent writes
# and are held through the following DDL in the caller's migration transaction.
DOWNGRADE_PREFLIGHT_SQL = r"""
LOCK TABLE financial_policy_versions, orders, order_items,
order_intake_receipts,
financial_accompaniment_refund_applications,
financial_accompaniment_management_reviews, financial_refund_intent_approvals,
financial_correction_requests, financial_refund_matches,
financial_refund_component_applications, financial_refund_original_assessments,
paid_selection_accepted_deliveries, financial_refund_liability_assessments
IN ACCESS EXCLUSIVE MODE;
DO $$ BEGIN
 IF EXISTS (SELECT 1 FROM financial_refund_liability_assessments
   WHERE status='covered_zero')
 OR EXISTS (SELECT 1 FROM financial_policy_versions WHERE
   COALESCE((rules->>'selection_minor')::numeric,50000)<>50000 OR
   COALESCE((rules->>'accompaniment_minor')::numeric,120000)<>120000)
 OR EXISTS (SELECT 1 FROM order_items WHERE selection_minor<>50000 OR
   accompaniment_minor NOT IN (0,120000))
 OR EXISTS (SELECT 1 FROM order_intake_receipts r JOIN orders o
   ON o.order_id=r.order_id WHERE o.bloggers_needed<>30 OR
   jsonb_array_length(r.result->'items')<>30 OR
   (SELECT count(*) FROM order_items i WHERE i.order_id=r.order_id)<>30 OR
   EXISTS (SELECT 1 FROM jsonb_array_elements(r.result->'items') i WHERE
     (i->>'selection_minor')::numeric<>50000 OR
     (i->>'accompaniment_minor')::numeric NOT IN (0,120000)))
 OR EXISTS (SELECT 1 FROM financial_accompaniment_refund_applications
   WHERE customer_target_minor>120000)
 OR EXISTS (SELECT 1 FROM financial_accompaniment_management_reviews
   WHERE customer_net_minor>120000)
 OR EXISTS (SELECT 1 FROM financial_refund_intent_approvals WHERE
   amount_minor NOT BETWEEN 50000 AND 1500000 OR jsonb_array_length(bundle)>30)
 OR EXISTS (SELECT 1 FROM financial_correction_requests
   WHERE jsonb_array_length(paid_item_ids)>30)
 OR EXISTS (SELECT 1 FROM financial_refund_matches
   WHERE jsonb_array_length(bundle)>30)
 OR EXISTS (SELECT 1 FROM financial_refund_component_applications
   WHERE gross_minor<>50000)
 OR EXISTS (SELECT 1 FROM financial_refund_original_assessments
   WHERE jsonb_array_length(new_ground_ids)>30)
 OR EXISTS (SELECT 1 FROM paid_selection_accepted_deliveries
   WHERE amount_minor<>50000)
 THEN RAISE EXCEPTION 'variable_tariff_downgrade_incompatible_history'
   USING ERRCODE='23514'; END IF;
END $$;
"""


DOWNGRADE_SQL = r"""

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
 SELECT * INTO intent FROM correction_match_capsule(app.match_id);
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
ALTER TABLE financial_refund_liability_assessments
DROP CONSTRAINT ck_correction_liability;
ALTER TABLE financial_refund_liability_assessments
ADD CONSTRAINT ck_correction_liability CHECK (
status IN ('pending_cancelled','covered_absence') AND
 target_minor>=0 AND already_cancelled_minor>=0 AND
 delta_minor=target_minor-already_cancelled_minor AND delta_minor>=0 AND
 (frozen_rate_bps IS NULL OR frozen_rate_bps BETWEEN 0 AND 10000));
DROP FUNCTION correction_zero_assessment_valid(
 uuid,uuid,uuid,uuid,uuid,uuid,bigint);
DROP TRIGGER financial_delivery_tariff_source ON
paid_selection_accepted_deliveries;
DROP FUNCTION financial_delivery_tariff_guard();
DROP TRIGGER financial_item_tariff_source ON order_items;
DROP FUNCTION financial_item_tariff_guard();
DROP TRIGGER financial_policy_tariff_source ON financial_policy_versions;
DROP FUNCTION financial_policy_tariff_guard();
ALTER TABLE financial_accompaniment_refund_applications DROP CONSTRAINT
ck_accompaniment_application_values;
ALTER TABLE financial_accompaniment_refund_applications ADD CONSTRAINT
ck_accompaniment_application_values CHECK (customer_target_minor BETWEEN 1 AND
120000 AND customer_delta_minor>0 AND
customer_delta_minor<=customer_target_minor AND manager_target_minor BETWEEN 0
AND 60000 AND manager_delta_minor BETWEEN 0 AND manager_target_minor AND
((work_version=0 AND assignment_id IS NULL AND stage IS NULL AND
manager_target_minor=0) OR (work_version>0 AND assignment_id IS NOT NULL AND
stage IS NOT NULL)));
ALTER TABLE financial_accompaniment_management_reviews DROP CONSTRAINT
ck_accompaniment_management_review;
ALTER TABLE financial_accompaniment_management_reviews ADD CONSTRAINT
ck_accompaniment_management_review CHECK (decision IN ('continue','cancel')
AND customer_net_minor BETWEEN 0 AND 120000 AND work_version>0);
ALTER TABLE financial_refund_intent_approvals DROP CONSTRAINT
ck_correction_approval_capsule;
ALTER TABLE financial_refund_intent_approvals ADD CONSTRAINT
ck_correction_approval_capsule CHECK (source_hash ~ '^[0-9a-f]{64}$' AND
currency='RUB' AND amount_minor BETWEEN 50000 AND 1500000 AND review_version>0
AND jsonb_typeof(source_capsule)='object' AND jsonb_typeof(bundle)='array' AND
jsonb_array_length(bundle) BETWEEN 1 AND 30);
ALTER TABLE financial_correction_requests DROP CONSTRAINT
ck_correction_request_items;
ALTER TABLE financial_correction_requests ADD CONSTRAINT
ck_correction_request_items CHECK (jsonb_typeof(paid_item_ids)='array' AND
jsonb_array_length(paid_item_ids) BETWEEN 1 AND 30);
ALTER TABLE financial_refund_matches DROP CONSTRAINT ck_correction_match;
ALTER TABLE financial_refund_matches ADD CONSTRAINT ck_correction_match CHECK
(amount_minor>0 AND currency='RUB' AND review_version>0 AND
jsonb_typeof(bundle)='array' AND jsonb_array_length(bundle) BETWEEN 1 AND 30);
ALTER TABLE financial_refund_component_applications DROP CONSTRAINT
ck_correction_component;
ALTER TABLE financial_refund_component_applications ADD CONSTRAINT
ck_correction_component CHECK (component='selection' AND currency='RUB' AND
gross_minor=50000 AND prior_refund_minor>=0 AND
new_refund_minor=prior_refund_minor+refund_minor AND
new_refund_minor<=gross_minor AND refund_minor=gross_minor);
ALTER TABLE financial_refund_original_assessments DROP CONSTRAINT
ck_refund_original_grounds;
ALTER TABLE financial_refund_original_assessments ADD CONSTRAINT
ck_refund_original_grounds CHECK (jsonb_typeof(new_ground_ids)='array' AND
jsonb_array_length(new_ground_ids) BETWEEN 1 AND 30);
ALTER TABLE paid_selection_accepted_deliveries DROP CONSTRAINT
ck_selection_accepted_value;
ALTER TABLE paid_selection_accepted_deliveries ADD CONSTRAINT
ck_selection_accepted_value CHECK (currency='RUB' AND amount_minor=50000 AND
length(trim(instagram_user_id))>0 AND length(trim(provider_reference))>0);
CREATE OR REPLACE FUNCTION intake_validate_source() RETURNS trigger
LANGUAGE plpgsql AS $$
DECLARE owner uuid; actual_count integer; matched_count integer;
BEGIN
    SELECT advertiser_id INTO owner FROM orders
        WHERE order_id=NEW.order_id AND created_at=NEW.requested_at;
    IF owner IS DISTINCT FROM NEW.client_id
       OR NEW.result->>'order_id' IS DISTINCT FROM NEW.order_id::text
       OR NEW.result->>'request_id' IS DISTINCT FROM NEW.request_id::text
       OR NEW.result->>'honorarium_payment' IS DISTINCT FROM 'paid_direct' THEN
        RAISE EXCEPTION 'intake_source_mismatch';
    END IF;
    SELECT count(*) INTO actual_count FROM order_items
        WHERE order_id=NEW.order_id;
    SELECT count(DISTINCT actual.paid_item_id) INTO matched_count
        FROM jsonb_array_elements(NEW.result->'items') requested
        JOIN order_items actual
          ON actual.paid_item_id=(requested->>'paid_item_id')::uuid
         AND actual.order_id=NEW.order_id
         AND actual.ordinal=(requested->>'ordinal')::integer
         AND actual.selection_minor=50000
         AND actual.selection_minor=(requested->>'selection_minor')::bigint
         AND actual.accompaniment_minor IN (0,120000)
         AND actual.accompaniment_minor=
             (requested->>'accompaniment_minor')::bigint
         AND actual.currency=NEW.result->>'currency'
         AND actual.policy_version=NEW.result->>'policy_version'
         AND actual.selection_due_at=
             (NEW.result->>'selection_due_at')::timestamptz
         AND actual.quote_payload->>'terms_reference'=
             NEW.result->>'terms_reference';
    IF actual_count <> 30 OR matched_count <> 30
       OR jsonb_array_length(NEW.result->'items') <> 30 THEN
        RAISE EXCEPTION 'intake_quote_mismatch';
    END IF;
    RETURN NEW;
END $$;
CREATE OR REPLACE FUNCTION accompaniment_validate_lead() RETURNS trigger
LANGUAGE plpgsql AS $$ DECLARE receipt record; selected jsonb;
BEGIN
    SELECT * INTO receipt FROM order_intake_receipts
        WHERE request_id=NEW.request_id;
    SELECT jsonb_agg((item->>'ordinal')::integer
        ORDER BY (item->>'ordinal')::integer) INTO selected
        FROM jsonb_array_elements(receipt.result->'items') item
        WHERE (item->>'accompaniment_minor')::bigint=120000;
    IF receipt.order_id IS DISTINCT FROM NEW.order_id
       OR receipt.client_id IS DISTINCT FROM NEW.client_id
       OR receipt.requested_at IS DISTINCT FROM NEW.requested_at
       OR receipt.result->>'lead_id' IS DISTINCT FROM NEW.lead_id::text
       OR selected IS NULL OR selected IS DISTINCT FROM NEW.selected_ordinals
       OR length(trim(NEW.contact_reference))=0 THEN
        RAISE EXCEPTION 'accompaniment_lead_source_mismatch';
    END IF;
    RETURN NEW;
END $$;
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
 OR NEW.customer_net_minor IS DISTINCT FROM 120000-app.customer_target_minor
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
  AND order_id=request.order_id AND currency='RUB' AND amount_minor=50000;
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
 OR ground.base_minor IS DISTINCT FROM 50000
 OR snapshot.payment_id IS DISTINCT FROM NEW.payment_id
 OR snapshot.referred_user_id::text IS DISTINCT FROM
capture.payload#>>'{capture,client_id}'
 OR snapshot.effective_at IS DISTINCT FROM
(capture.payload#>>'{capture,captured_at}')::timestamptz
 OR ground.amount_minor IS DISTINCT FROM
(50000::bigint*snapshot.rate_bps+5000)/10000
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
 OR jsonb_array_length(authority->'bundle') NOT BETWEEN 1 AND 30
 OR jsonb_array_length(authority->'bundle')*50000 IS DISTINCT FROM
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
 OR item.selection_minor IS DISTINCT FROM 50000 OR item.accompaniment_minor NOT
 IN (0,120000)
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
 OR jsonb_array_length(intake.result->'items') IS DISTINCT FROM 30
 OR allocation.payment_id IS DISTINCT FROM payment.payment_id
 OR allocation.order_id IS DISTINCT FROM request.order_id OR
 allocation.paid_item_id IS DISTINCT FROM item.paid_item_id
 OR allocation.component IS DISTINCT FROM 'selection' OR
 allocation.amount_minor IS DISTINCT FROM 50000
 OR allocation.currency IS DISTINCT FROM 'RUB'
 OR b->>'payment_id' IS DISTINCT FROM payment.payment_id::text
 OR b->'gross_minor' IS DISTINCT FROM '50000'::jsonb OR b->>'currency' IS
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
 jsonb_array_elements_text(request.paid_item_ids)) AND
correction_original_ground_visible(id,request.case_id,authority->>'source_hash');
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
 FROM financial_obligations WHERE order_id=request.order_id AND
correction_original_ground_visible(id,request.case_id,authority->>'source_hash')),'[]'),
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
"""


def upgrade():
    op.execute(sa.text(UPGRADE_SQL))


def downgrade():
    op.execute(sa.text(DOWNGRADE_PREFLIGHT_SQL))
    op.execute(sa.text(DOWNGRADE_SQL))
