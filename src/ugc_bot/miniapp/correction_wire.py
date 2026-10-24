"""Exact signed observation amounts and private correction error boundaries."""

import re

from ugc_bot.domain.financial import MAX_MINOR

PUBLIC_CORRECTION_CODES = frozenset(
    {
        "correction_active_actor_required",
        "correction_active_admin_required",
        "correction_application_review_required",
        "correction_approved_review_required",
        "correction_approved_source_conflict",
        "correction_capture_unavailable",
        "correction_case_scope_invalid",
        "correction_compensation_assessment_required",
        "correction_creator_manager_ground_unsupported",
        "correction_due_agreement_unavailable",
        "correction_duplicate_identity",
        "correction_exact_bundle_required",
        "correction_full_bundle_required",
        "correction_hash_invalid",
        "correction_identity_invalid",
        "correction_intent_ambiguous",
        "correction_match_approval_unavailable",
        "correction_minor_invalid",
        "correction_observation_economics_unavailable",
        "correction_observation_scope_conflict",
        "correction_observed_minor_invalid",
        "correction_order_missing",
        "correction_original_payment_unavailable",
        "correction_own_client_required",
        "correction_physical_proof_conflict",
        "correction_physical_proof_unavailable",
        "correction_provenance_required",
        "correction_read_request_invalid",
        "correction_request_exists",
        "correction_request_scope_invalid",
        "correction_scope_changed_retry_required",
        "correction_selected_routing_unavailable",
        "correction_selection_required",
        "correction_selection_already_delivered",
        "correction_selection_due_not_passed",
        "correction_selection_due_unavailable",
        "correction_selection_previously_assigned",
        "correction_full_selection_component_required",
        "correction_source_conflict",
        "correction_source_unavailable",
        "correction_state_unavailable",
        "correction_unavailable",
        "correction_version_conflict",
        "correction_version_invalid",
        "financial_corrections_disabled",
        "financial_principal_changed",
        "idempotency_payload_conflict",
    }
)


def public_correction_code(value):
    code = str(value)
    return code if code in PUBLIC_CORRECTION_CODES else "correction_unavailable"


def parse_observed_minor(value):
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or not re.fullmatch(r"(?:0|-?[1-9][0-9]*)", value)
        or len(value.lstrip("-")) > 19
    ):
        raise ValueError("correction_observed_minor_invalid")
    number = int(value)
    if not -(MAX_MINOR + 1) <= number <= MAX_MINOR:
        raise ValueError("correction_observed_minor_invalid")
    return number


def _money(value):
    if value is None:
        return None
    if type(value) is int and -(MAX_MINOR + 1) <= value <= MAX_MINOR:
        return str(value)
    try:
        parse_observed_minor(value)
    except ValueError:
        raise ValueError("correction_source_unavailable") from None
    return value


def correction_to_wire(value):
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key == "blockers" and isinstance(item, (list, tuple)):
                result[key] = [public_correction_code(v) for v in item]
            elif key.endswith("_minor"):
                result[key] = _money(item)
            else:
                result[key] = correction_to_wire(item)
        return result
    if isinstance(value, (list, tuple)):
        return [correction_to_wire(item) for item in value]
    return value
