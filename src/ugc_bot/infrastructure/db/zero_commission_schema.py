"""Proof of a captured, completed zero referral assessment for correction."""

ZERO_ASSESSMENT_SQL = r"""
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
"""
