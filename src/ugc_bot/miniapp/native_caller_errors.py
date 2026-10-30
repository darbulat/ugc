"""Exact public errors for the bounded intake and collaboration callers."""

from fastapi import HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute

from ugc_bot.application.errors import OrderCreationError

SHARED_CODES = {
    "financial_principal_changed": 403,
    "financial_session_invalid": 401,
    "existing_financial_account_required": 404,
    "financial_unavailable": 503,
    "financial_disabled": 503,
    "idempotency_payload_conflict": 409,
}
INTAKE_CODES = SHARED_CODES | {
    "pilot_policy_superseded": 409,
    "active_advertiser_required": 403,
    "intake_admin_required": 403,
    "invalid_intake_funnel_stage": 422,
    "invalid_intake_funnel_identity": 422,
    "client_not_allowlisted": 403,
    **dict.fromkeys(
        (
            "client_identity_required",
            "intake_provenance_required",
            "invalid_direct_honorarium",
            "invalid_order_targeting",
            "invalid_targeting_range",
            "invalid_service_mode",
            "self_service_has_no_accompaniment",
            "invalid_accompaniment_ordinals",
            "aware_timestamp_required",
            "unpublished_currency",
            "approved_policy_required",
            "legacy_order_not_eligible",
            "selection_refund_window_required",
            "agreed_selection_due_at_required",
            "published_terms_required",
            "approval_after_activation",
            "policy_feature_disabled",
            "positive_item_count_required",
            "invalid_accompaniment_ordinal",
            "quote_terms_and_provenance_required",
            "Product link is required.",
            "Offer text is required.",
            "Price cannot be negative.",
            "Price must be positive when no barter.",
            "Invalid bloggers count.",
            "Advertiser profile is not set.",
            "Blocked users cannot create orders.",
            "Paused users cannot create orders.",
        ),
        400,
    ),
}
COLLABORATION_CODES = SHARED_CODES | {
    **dict.fromkeys(
        (
            "active_actor_required",
            "active_admin_required",
            "collaboration_party_required",
            "assignment_actor_required",
            "client_consent_required",
            "collaboration_view_forbidden",
            "authenticated_actor_required",
            "collaboration_resolution_admin_required",
            "ambiguous_actor",
            "trusted_collaboration_producer_required",
        ),
        403,
    ),
    **dict.fromkeys(
        (
            "assignment_not_found",
            "assignment_not_current",
            "captured_selection_required",
            "distinct_collaboration_parties_required",
            "collaboration_scope_changed",
            "collaboration_version_conflict",
            "collaboration_time_conflict",
            "collaboration_not_found",
            "collaboration_already_assigned",
            "unsupported_collaboration_command",
            "command_key_required",
            "collaboration_version_required",
            "assignment_identity_required",
            "agreed_terms_required",
            "extension_consent_and_reason_required",
            "confirmation_request_state_conflict",
            "collaboration_identity_required",
            "agreed_due_at_required",
            "due_version_required",
            "collaboration_state_conflict",
            "opposite_party_required",
            "claim_window_closed",
            "evidence_required",
            "objection_window_closed",
            "dispute_reason_required",
            "dispute_resolution_evidence_required",
            "resolution_evidence_required",
            "invalid_dispute_page",
            "dispute_resolution_reason_required",
            "due_version_conflict",
            "aware_timestamp_required",
        ),
        409,
    ),
}


class _NativeCallerRoute(APIRoute):
    codes: dict[str, int]
    prefix: str
    http_pairs: dict[tuple[str, int], int]

    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request):
            try:
                response = await original(request)
            except RequestValidationError:
                response = self._error(f"{self.prefix}_request_invalid", 422)
            except HTTPException as error:
                code = error.detail
                if type(code) is str and code in self.codes:
                    status = self.codes[code]
                    supplied_status = error.status_code
                    if type(supplied_status) is int:
                        status = self.http_pairs.get(
                            (code, supplied_status), status
                        )
                    response = self._error(code, status)
                elif (
                    type(code) is str
                    and code == f"{self.prefix}_request_invalid"
                ):
                    response = self._error(code, 422)
                else:
                    response = self._error(f"{self.prefix}_unavailable", 503)
            except (PermissionError, ValueError, OrderCreationError) as error:
                code = error.args[0] if len(error.args) == 1 else None
                response = (
                    self._error(code, self.codes[code])
                    if type(code) is str and code in self.codes
                    else self._error(f"{self.prefix}_unavailable", 503)
                )
            except Exception:
                response = self._error(f"{self.prefix}_unavailable", 503)
            response.headers["Cache-Control"] = "no-store"
            return response

        return handler

    @staticmethod
    def _error(code, status):
        return JSONResponse({"detail": code}, status_code=status)


class NoStoreIntakeRoute(_NativeCallerRoute):
    codes = INTAKE_CODES
    http_pairs = {
        (code, status): status for code, status in INTAKE_CODES.items()
    }
    prefix = "intake"


class NoStoreCollaborationRoute(_NativeCallerRoute):
    codes = COLLABORATION_CODES
    http_pairs = {
        **{
            (code, status): status
            for code, status in COLLABORATION_CODES.items()
        },
        ("collaboration_not_found", 404): 404,
    }
    prefix = "collaboration"


_SNAPSHOT_NATIVE_CODES = {
    "financial_principal_changed": 403,
    "financial_session_invalid": 401,
    "existing_financial_account_required": 404,
    "financial_unavailable": 503,
    "financial_disabled": 503,
}
PARTNER_CODES = _SNAPSHOT_NATIVE_CODES | {
    "partner_account_unavailable": 403,
    "partner_scope_mismatch": 403,
    "partner_not_found": 404,
}
SELECTION_CODES = _SNAPSHOT_NATIVE_CODES | {
    "selection_close_forbidden": 403,
    "selection_refund_rules_required": 409,
    "selection_closure_evidence_required": 422,
    "selection_fact_in_future": 409,
    "financial_scope_changed_retry_required": 409,
    "selection_client_inactive": 403,
    "selection_client_role_required": 403,
    "selection_order_not_found": 404,
    "selection_order_has_no_financial_version": 503,
    "selection_history_unavailable": 503,
    "selection_delivery_scope_mismatch": 503,
}
SUMMARY_CODES = _SNAPSHOT_NATIVE_CODES | {
    "summary_actor_inactive": 403,
    "summary_not_found": 404,
    "summary_history_unavailable": 503,
    "summary_delivery_scope_mismatch": 503,
}


class NoStorePartnerRoute(_NativeCallerRoute):
    codes = PARTNER_CODES
    http_pairs = {
        (code, status): status for code, status in PARTNER_CODES.items()
    }
    prefix = "partner"


class NoStoreSelectionRoute(_NativeCallerRoute):
    codes = SELECTION_CODES
    http_pairs = {
        (code, status): status for code, status in SELECTION_CODES.items()
    }
    prefix = "selection"


class NoStoreSummaryRoute(_NativeCallerRoute):
    codes = SUMMARY_CODES
    http_pairs = {
        (code, status): status for code, status in SUMMARY_CODES.items()
    }
    prefix = "summary"
