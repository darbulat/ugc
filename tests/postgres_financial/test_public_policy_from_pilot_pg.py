"""Publication and exact retries against isolated real PostgreSQL."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from tests.application.services.test_public_policy_from_pilot import (
    pilot,
    request,
)
from tests.postgres_financial.test_refund_policy_configuration import (
    seed as _source_seed,
)
from ugc_bot.infrastructure.db.models import (
    FinancialPolicyVersionModel,
    UserModel,
)
from ugc_bot.infrastructure.db.session import SessionTransactionManager
from ugc_bot.public_policy_from_pilot import PUBLIC_VERSION, execute


@pytest.fixture
def seed(financial_pg_engine, request):
    return _source_seed.__wrapped__(financial_pg_engine, request)


@pytest.mark.asyncio
async def test_preview_publish_retry_conflict_and_revocation(
    financial_pg_engine, seed
):
    original = pilot()
    with Session(financial_pg_engine) as db, db.begin():
        db.add(
            FinancialPolicyVersionModel(
                version=original.version,
                approved_by=seed["user"],
                approved_at=original.approved_at,
                effective_from=original.effective_from,
                refund_window_seconds=original.refund_window_seconds,
                rules=original.rules,
            )
        )
    async_engine = create_async_engine(financial_pg_engine.url)
    transactions = SessionTransactionManager(async_sessionmaker(async_engine))
    args = request(
        actor_id=seed["user"],
        effective_from=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    try:
        preview = await execute(args, transactions, publish=False)
        assert preview["state"] == "preview"
        with Session(financial_pg_engine) as db:
            assert db.get(FinancialPolicyVersionModel, PUBLIC_VERSION) is None
        published = await execute(args, transactions, publish=True)
        assert published["state"] == "published"
        repeat = await execute(args, transactions, publish=True)
        assert repeat["state"] == "already_published"
        assert repeat["approved_at"] == published["approved_at"]
        with pytest.raises(ValueError, match="policy_version_conflict"):
            await execute(
                replace(args, terms_sha256="b" * 64), transactions, publish=True
            )
        with pytest.raises(ValueError, match="policy_version_conflict"):
            changed_rules = replace(
                args.refund_rules,
                selection_closure_mode="all_positions_resolved",
            )
            await execute(
                replace(args, refund_rules=changed_rules),
                transactions,
                publish=True,
            )
        with Session(financial_pg_engine) as db, db.begin():
            db.get(UserModel, seed["user"]).admin = False
        with pytest.raises(PermissionError, match="active_admin_required"):
            await execute(args, transactions, publish=True)
        with Session(financial_pg_engine) as db:
            saved = db.scalar(
                select(FinancialPolicyVersionModel).where(
                    FinancialPolicyVersionModel.version == PUBLIC_VERSION
                )
            )
            assert saved.rules["all_clients"] is True
            assert (
                saved.rules["refund_rules"] == args.refund_rules.to_document()
            )
            assert (
                db.get(FinancialPolicyVersionModel, original.version).rules
                == original.rules
            )
    finally:
        await async_engine.dispose()
