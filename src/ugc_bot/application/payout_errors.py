"""Bounded public payout error codes; arbitrary exception text is private."""

from ugc_bot.application.errors import LegacyPayoutBlockedError

# Explicit server-defined codes only. Never admit a prefix or caller text.
PUBLIC_PAYOUT_CODES = frozenset(
    {
        "active_actor_required",
        "active_admin_required",
        "aware_timestamp_required",
        "financial_payouts_disabled",
        "financial_principal_changed",
        "idempotency_payload_conflict",
        "payout_acceptance_required",
        "payout_accepted_terms_and_fields_required",
        "payout_amount_invalid",
        "payout_available_insufficient",
        "payout_bank_account_configuration_required",
        "payout_bank_evidence_invalid",
        "payout_bank_reconciliation_required",
        "payout_bank_source_configuration_required",
        "payout_command_unknown",
        "payout_debt_manual_review_required",
        "payout_document_invalid",
        "payout_document_mismatch",
        "payout_encryption_configuration_required",
        "payout_evidence_reference_required",
        "payout_execution_scope_invalid",
        "payout_field_definitions_invalid",
        "payout_history_authority_review_required",
        "payout_identity_invalid",
        "payout_item_corrected_review_required",
        "payout_legal_reference_required",
        "payout_money_application_refused",
        "payout_not_found",
        "payout_operation_key_required",
        "payout_operation_unavailable",
        "payout_own_or_admin_required",
        "payout_own_requisites_required",
        "payout_readable_acceptance_required",
        "payout_readable_terms_required",
        "payout_reason_required",
        "payout_requirements_changed",
        "payout_requirements_invalid",
        "payout_requisites_authentication_failed",
        "payout_requisites_fields_invalid",
        "payout_requisites_permitted_value_required",
        "payout_review_approval_required",
        "payout_sla_not_overdue",
        "payout_state_not_reviewable",
        "payout_state_reconciliation_required",
        "payout_terms_reference_required",
        "payout_version_conflict",
        "published_payout_requirements_required",
        "recipient_not_found",
        "reconciliation_mismatch_audit_required",
        "unpublished_currency",
        "work_disputed",
    }
)


PUBLIC_PAYOUT_BLOCK_CODES = PUBLIC_PAYOUT_CODES | frozenset(
    {
        "",
        "legacy_payout_blocked",
        "payout_unavailable",
        "payout_stale_execution",
        "payout_money_application_review_required",
        "payout_bank_amount_or_currency_mismatch",
        "payout_bank_account_mismatch",
        "payout_bank_recipient_mismatch",
        "payout_bank_settlement_proof_incomplete",
        "payout_bank_reference_reused",
    }
)


def public_payout_code(error: ValueError) -> str:
    if isinstance(error, LegacyPayoutBlockedError):
        return "legacy_payout_blocked"
    code = str(error)
    return code if code in PUBLIC_PAYOUT_CODES else "payout_unavailable"
