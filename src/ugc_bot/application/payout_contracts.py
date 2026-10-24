"""Pure readable-contract validation and immutable command compatibility."""

import hashlib
import re
from dataclasses import asdict
from datetime import datetime
from uuid import UUID

from ugc_bot.application.payout_contract_ports import (
    PayoutFieldDefinition,
    TermsDocumentInput,
)
from ugc_bot.application.payout_errors import PUBLIC_PAYOUT_BLOCK_CODES


def command_payload(command):
    payload = asdict(command)
    fields = {
        "PublishPayoutRequirements": ("document", "field_definitions"),
        "StorePayoutRequisites": (
            "accepted_document_id",
            "accepted_document_hash",
            "accepted",
        ),
    }.get(type(command).__name__, ())
    for name in fields:
        if payload.get(name) is None:
            payload.pop(name, None)
    return payload


def document_hash(text):
    if (
        not isinstance(text, str)
        or not text.strip()
        or len(text.encode()) > 1000000
    ):
        raise ValueError("payout_readable_terms_required")
    return hashlib.sha256(text.encode()).hexdigest()


def document_input(value):
    if not isinstance(value, TermsDocumentInput):
        raise ValueError("payout_readable_terms_required")
    if value.document_id is not None:
        if (
            not isinstance(value.document_id, UUID)
            or value.document_id.int == 0
            or value.content_text is not None
            or value.source_locale is not None
        ):
            raise ValueError("payout_document_invalid")
        return dict(document_id=value.document_id)
    digest = document_hash(value.content_text)
    if not isinstance(value.source_locale, str) or not re.fullmatch(
        r"[A-Za-z][A-Za-z0-9-]{1,34}", value.source_locale
    ):
        raise ValueError("payout_document_invalid")
    return dict(
        content_text=value.content_text,
        source_locale=value.source_locale,
        sha256=digest,
    )


def field_definitions(values, required, locale):
    if not isinstance(values, (tuple, list)) or len(values) != len(required):
        raise ValueError("payout_field_definitions_invalid")
    found = {}
    for definition in values:
        if (
            not isinstance(definition, PayoutFieldDefinition)
            or definition.key in found
            or definition.key not in required
        ):
            raise ValueError("payout_field_definitions_invalid")
        for mapping in (definition.labels, definition.help):
            if not isinstance(mapping, dict) or any(
                not isinstance(k, str)
                or not re.fullmatch(r"[A-Za-z][A-Za-z0-9-]{1,34}", k)
                or not isinstance(v, str)
                or not v.strip()
                or len(v) > 2000
                for k, v in mapping.items()
            ):
                raise ValueError("payout_field_definitions_invalid")
        if locale not in definition.labels:
            raise ValueError("payout_field_definitions_invalid")
        allowed = definition.allowed_values
        if allowed is not None and (
            not isinstance(allowed, (tuple, list))
            or not allowed
            or any(
                not isinstance(v, str) or not v.strip() or len(v) > 2000
                for v in allowed
            )
            or len(allowed) != len(set(allowed))
        ):
            raise ValueError("payout_field_definitions_invalid")
        found[definition.key] = asdict(definition)
    return [found[key] for key in required]


def require_acceptance(command, contract):
    if contract is None:
        raise ValueError("payout_readable_terms_required")
    document = contract["document"]
    if command.accepted is not True:
        raise ValueError("payout_acceptance_required")
    if (
        str(command.accepted_document_id) != str(document["document_id"])
        or command.accepted_document_hash != document["sha256"]
    ):
        raise ValueError("payout_document_mismatch")
    for definition in contract["field_definitions"]:
        allowed = definition["allowed_values"]
        if (
            allowed is not None
            and command.details[definition["key"]] not in allowed
        ):
            raise ValueError("payout_requisites_permitted_value_required")


def owner_receipt(action, result):
    """An explicit typed whitelist; no arbitrary nested saved JSON escapes."""
    if not isinstance(result, dict):
        raise ValueError("payout_operation_unavailable")
    keys = {
        "requisites_id",
        "requirements_id",
        "masked_label",
        "document_id",
        "document_hash",
    }
    if action == "RequestPayout":
        keys = {
            "request_id",
            "requisites_id",
            "requirements_id",
            "amount_minor",
            "currency",
            "requested_at",
            "deadline_at",
            "version",
            "state",
            "execution_id",
            "block_reason",
            "masked_label",
        }
    elif action != "StorePayoutRequisites":
        raise ValueError("payout_operation_unavailable")
    safe = {k: v for k, v in result.items() if k in keys}
    try:
        _validate_receipt_scope(safe, action)
        if action == "RequestPayout":
            _validate_request_receipt(safe)
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        raise ValueError("payout_operation_unavailable") from error
    return safe


def _validate_receipt_scope(safe, action):
    for key in ("requisites_id", "requirements_id") + (
        ("request_id",) if action == "RequestPayout" else ()
    ):
        if UUID(str(safe[key])).int == 0:
            raise ValueError()
    for key in ("document_id", "execution_id"):
        if safe.get(key) is not None and UUID(str(safe[key])).int == 0:
            raise ValueError()
    if "masked_label" in safe and (
        not isinstance(safe["masked_label"], str)
        or not re.fullmatch(r"••••[\s\S]{0,4}", safe["masked_label"])
    ):
        raise ValueError()
    if "document_hash" in safe and not re.fullmatch(
        r"[0-9a-f]{64}", safe["document_hash"]
    ):
        raise ValueError()


def _validate_request_receipt(safe):
    from ugc_bot.domain.financial import MAX_MINOR

    if (
        type(safe["amount_minor"]) is not int
        or not 0 < safe["amount_minor"] <= MAX_MINOR
        or safe["currency"] != "RUB"
        or type(safe["version"]) is not int
        or safe["version"] < 1
        or safe["state"]
        not in (
            "reserved",
            "approved",
            "blocked",
            "executing",
            "unknown",
            "failed",
            "paid",
            "rejected",
        )
        or not isinstance(safe["block_reason"], str)
        or safe["block_reason"] not in PUBLIC_PAYOUT_BLOCK_CODES
    ):
        raise ValueError()
    for key in ("requested_at", "deadline_at"):
        if datetime.fromisoformat(safe[key]).tzinfo is None:
            raise ValueError()
