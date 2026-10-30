"""Preview or explicitly publish the public policy derived from the pilot.

The actor and basis are supplied by the operator; this CLI does not verify a
cryptographic signature or invent evidence of an administrator's approval.
"""

import argparse
import asyncio
import hashlib
import json
import re
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen
from uuid import UUID

from sqlalchemy import select, text

from ugc_bot.application.services.financial_policy_service import (
    FinancialPolicyService,
)
from ugc_bot.domain.enums import UserStatus
from ugc_bot.domain.financial import utc
from ugc_bot.domain.refund_rules import RefundRules
from ugc_bot.infrastructure.db.models import (
    FinancialPolicyVersionModel,
    UserModel,
)
from ugc_bot.infrastructure.db.repositories.financial_policy import (
    SqlAlchemyFinancialPolicyRepository,
    decode_policy_version,
)

SOURCE_VERSION = "umc-financial-v1.2-pilot-2026-10-24"
PUBLIC_VERSION = "umc-financial-v1.2-public-2026-10-30"
SOURCE_URL = (
    f"https://bot.usemycontent.ru/financial-policy/{SOURCE_VERSION}.html"
)
PUBLIC_URL = (
    f"https://bot.usemycontent.ru/financial-policy/{PUBLIC_VERSION}.html"
)
SOURCE_SHA256 = (
    "954b3b932236d32108e9a3335cf98321023b24c4c615736d79ecaea02a0f6dd7"
)


@dataclass(frozen=True)
class PublicationRequest:
    version: str
    actor_id: UUID
    effective_from: datetime
    terms_url: str
    terms_sha256: str
    approval_reference: str
    refund_rules: RefundRules

    def validate(self) -> None:
        if self.version != PUBLIC_VERSION or self.terms_url != PUBLIC_URL:
            raise ValueError("public_policy_identity_mismatch")
        if not isinstance(self.refund_rules, RefundRules):
            raise ValueError("refund_rules_required")
        if (
            self.refund_rules.selection_refund_window_seconds != 604800
            or self.refund_rules.selection_refund_window_anchor
            != "item_delivered"
        ):
            raise ValueError("refund_rules_pilot_window_mismatch")
        if not isinstance(self.actor_id, UUID) or self.actor_id.int == 0:
            raise ValueError("active_admin_required")
        utc(self.effective_from)
        if not isinstance(self.terms_sha256, str) or not re.fullmatch(
            r"[0-9a-f]{64}", self.terms_sha256
        ):
            raise ValueError("terms_hash_required")
        if (
            not isinstance(self.approval_reference, str)
            or not self.approval_reference.strip()
            or self.approval_reference != self.approval_reference.strip()
            or len(self.approval_reference) > 1024
        ):
            raise ValueError("approval_reference_required")


def parse_refund_rules(raw: str) -> RefundRules:
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate_refund_rule_key")
            result[key] = value
        return result

    if not isinstance(raw, str):
        raise ValueError("refund_rules_required")
    try:
        rules = RefundRules.from_document(
            json.loads(raw, object_pairs_hook=unique_pairs)
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid_refund_rules_document") from exc
    if (
        rules.selection_refund_window_seconds != 604800
        or rules.selection_refund_window_anchor != "item_delivered"
    ):
        raise ValueError("refund_rules_pilot_window_mismatch")
    return rules


def build_public_rules(source, request: PublicationRequest) -> dict:
    request.validate()
    if source is None or source.version != SOURCE_VERSION:
        raise ValueError("source_policy_mismatch")
    rules = source.rules
    if not isinstance(rules, dict):
        raise ValueError("source_policy_mismatch")
    expected = {
        "terms_reference": SOURCE_URL,
        "terms_sha256": SOURCE_SHA256,
        "approval_scope": "owner_product_rules_and_two_account_pilot_only",
        "selection_minor": 50000,
        "accompaniment_minor": 120000,
        "currency": "RUB",
        "hold_seconds": 1209600,
        "selection_refund_window_anchor": "per_item_delivery_accepted_at",
    }
    if (
        source.refund_window_seconds != 604800
        or any(
            type(rules.get(k)) is not type(v) or rules.get(k) != v
            for k, v in expected.items()
        )
        or rules.get("all_clients", False) is not False
        or not isinstance(rules.get("allowed_clients"), list)
        or len(rules["allowed_clients"]) != 2
        or source.approved_by is None
        or source.approved_at is None
        or source.effective_from is None
        or utc(source.approved_at) > utc(source.effective_from)
    ):
        raise ValueError("source_policy_mismatch")
    try:
        source_decoded = decode_policy_version(source)
        FinancialPolicyService._approved_policy(source_decoded, SOURCE_VERSION)
    except (TypeError, ValueError) as exc:
        raise ValueError("source_policy_mismatch") from exc
    if source_decoded.refund_rules is not None:
        raise ValueError("source_policy_mismatch")
    # Drop pilot-specific authorization claims, never transfer old identities
    # to the new act of approval. Preserve all other economic rules as-is.
    result = deepcopy(rules)
    for key in (
        "source_request_channel",
        "source_request_observed_at",
        "source_approver_telegram_id",
        "second_participant_approval",
        "financial_activation_authorized",
    ):
        result.pop(key, None)
    result.update(
        allowed_clients=[],
        all_clients=True,
        terms_reference=PUBLIC_URL,
        terms_sha256=request.terms_sha256,
        approval_scope="public_customer_policy",
        approval_reference=request.approval_reference,
        source_policy_version=SOURCE_VERSION,
        refund_rules=request.refund_rules.to_document(),
    )
    return result


def checked_terms(path: Path, expected_sha256: str, *, published: bool) -> None:
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise ValueError("local_terms_hash_mismatch")
    if published:
        with urlopen(PUBLIC_URL, timeout=15) as response:
            if response.status != 200 or response.url != PUBLIC_URL:
                raise ValueError("public_terms_url_mismatch")
            public_data = response.read(1_000_001)
        if (
            len(public_data) > 1_000_000
            or hashlib.sha256(public_data).hexdigest() != expected_sha256
        ):
            raise ValueError("public_terms_hash_mismatch")


async def execute(
    request: PublicationRequest, transactions, *, publish: bool
) -> dict:
    request.validate()
    repo = SqlAlchemyFinancialPolicyRepository()
    async with transactions.transaction() as session:
        if not publish:
            await session.execute(text("SET TRANSACTION READ ONLY"))
            actor = (
                await session.execute(
                    select(UserModel.admin, UserModel.status).where(
                        UserModel.user_id == request.actor_id
                    )
                )
            ).one_or_none()
            if (
                not actor
                or not actor.admin
                or actor.status != UserStatus.ACTIVE
            ):
                raise PermissionError("active_admin_required")
        else:
            if not await repo.lock_active_admin(
                request.actor_id, session=session
            ):
                raise PermissionError("active_admin_required")
            await repo.lock_version(request.version, session=session)
        source = await repo.get(SOURCE_VERSION, session=session)
        if source is None:
            raise ValueError("source_policy_mismatch")
        rules = build_public_rules(source, request)
        effective = utc(request.effective_from)
        current = await repo.get(request.version, session=session)
        if current is not None:
            if (
                current.approved_by != request.actor_id
                or utc(current.effective_from) != effective
                or current.refund_window_seconds != source.refund_window_seconds
                or current.rules != rules
                or current.approved_at is None
                or utc(current.approved_at) > effective
            ):
                raise ValueError("policy_version_conflict")
            approved_at = utc(current.approved_at)
            state = "already_published"
        elif publish:
            approved_at = datetime.now(timezone.utc)
            if effective < approved_at:
                raise ValueError("approval_after_activation")
            row = FinancialPolicyVersionModel(
                version=request.version,
                approved_by=request.actor_id,
                approved_at=approved_at,
                effective_from=effective,
                refund_window_seconds=source.refund_window_seconds,
                rules=rules,
            )
            decoded = decode_policy_version(row)
            if (
                not decoded.all_clients
                or decoded.refund_rules != request.refund_rules
            ):
                raise ValueError("public_policy_decode_mismatch")
            await repo.add(row, session=session)
            state = "published"
        else:
            approved_at = None
            state = "preview"
        return {
            "state": state,
            "version": request.version,
            "approved_by": str(request.actor_id),
            "approved_at": approved_at.isoformat() if approved_at else None,
            "effective_from": effective.isoformat(),
            "refund_window_seconds": source.refund_window_seconds,
            "rules": rules,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--approved-by", required=True, type=UUID)
    parser.add_argument("--approval-reference", required=True)
    parser.add_argument("--effective-from", required=True)
    parser.add_argument("--terms-file", required=True, type=Path)
    parser.add_argument("--terms-sha256", required=True)
    parser.add_argument("--refund-rules-json", required=True)
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args(argv)
    try:
        request = PublicationRequest(
            PUBLIC_VERSION,
            args.approved_by,
            datetime.fromisoformat(args.effective_from),
            PUBLIC_URL,
            args.terms_sha256,
            args.approval_reference,
            parse_refund_rules(args.refund_rules_json),
        )
        request.validate()
        checked_terms(
            args.terms_file, request.terms_sha256, published=args.publish
        )
        from ugc_bot.config import load_config
        from ugc_bot.container import Container

        container = Container(load_config())

        async def run():
            try:
                if container.transaction_manager is None:
                    raise ValueError("policy_database_required")
                return await execute(
                    request, container.transaction_manager, publish=args.publish
                )
            finally:
                await container.dispose()

        result = asyncio.run(run())
    except (ValueError, PermissionError, OSError) as exc:
        parser.error(str(exc))
    except Exception as exc:
        # Avoid leaking database credentials or private SQL in driver errors.
        parser.error(f"publication_failed:{type(exc).__name__}")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
