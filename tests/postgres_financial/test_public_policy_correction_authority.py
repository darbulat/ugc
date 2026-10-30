"""A genuine public-policy correction is protected by PostgreSQL authority."""

import json
from datetime import timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from tests.helpers.correction_approval_pg import ApprovalRuntime, create_match
from tests.helpers.corrections import captured_order
from tests.helpers.factories import (
    create_test_advertiser_profile,
    create_test_user,
)
from tests.postgres_financial.test_order_intake import intake_env as intake_env
from ugc_bot.infrastructure.db.models import FinancialPolicyVersionModel
from ugc_bot.infrastructure.db.repositories.financial_capture import intent_id

__all__ = ["intake_env"]


@pytest.mark.asyncio
async def test_real_public_correction_guard_rejects_forged_access_scopes(
    intake_env,
):
    env = intake_env.copy()
    client = await create_test_user(
        env["repos"]["user_repo"],
        external_id=str(uuid4().int % 10**12 + 1),
        country="ru",
    )
    await create_test_advertiser_profile(
        env["repos"]["advertiser_repo"], client.user_id
    )
    env["user"] = client
    version = "public-correction-" + uuid4().hex
    with Session(env["pg"]) as db, db.begin():
        pilot = db.get(FinancialPolicyVersionModel, env["policy"])
        assert str(client.user_id) not in pilot.rules["allowed_clients"]
        db.add(
            FinancialPolicyVersionModel(
                version=version,
                approved_by=env["admin"].user_id,
                approved_at=env["clock"].at - timedelta(days=2),
                effective_from=env["clock"].at - timedelta(days=1),
                refund_window_seconds=3600,
                rules={
                    "terms_reference": "terms:synthetic-public",
                    "allowed_clients": [],
                    "all_clients": True,
                },
            )
        )
    env["policy"] = version
    facts = await captured_order(env)
    facts["invoice_id"] = intent_id(facts["order"].order_id)
    rt = ApprovalRuntime(env, facts)
    _, approved, _, match = await create_match(rt)
    assert match["approval_id"] == approved["approval_id"]
    approval_id = UUID(approved["approval_id"])
    query = text(
        "SELECT correction_validate_authority(to_jsonb(a)) "
        "FROM financial_refund_intent_approvals a WHERE a.approval_id=:id"
    )
    with env["pg"].connect() as db:
        assert db.execute(query, {"id": approval_id}).one()
    # A prior whitelist-only policy remains valid for the listed owner.
    with env["pg"].connect() as db:
        transaction = db.begin()
        try:
            db.execute(text("SET LOCAL session_replication_role = replica"))
            db.execute(
                text(
                    "UPDATE financial_policy_versions SET rules = "
                    "(rules - 'all_clients') || CAST(:change AS jsonb) "
                    "WHERE version=:version"
                ),
                {
                    "change": json.dumps(
                        {"allowed_clients": [str(client.user_id)]}
                    ),
                    "version": version,
                },
            )
            db.execute(text("SET LOCAL session_replication_role = origin"))
            assert db.execute(query, {"id": approval_id}).one()
        finally:
            transaction.rollback()
    # Change the immutable fact only inside rolled-back test transactions. The
    # guard runs with triggers restored, using the genuine approval evidence.
    for rules in (
        {"all_clients": True, "allowed_clients": [str(client.user_id)]},
        {"all_clients": "true", "allowed_clients": [str(client.user_id)]},
        {"all_clients": None, "allowed_clients": [str(client.user_id)]},
        {"all_clients": True, "allowed_clients": {}},
        {"all_clients": False, "allowed_clients": []},
        {"all_clients": False, "allowed_clients": [str(client.user_id), 123]},
    ):
        with env["pg"].connect() as db:
            transaction = db.begin()
            try:
                db.execute(text("SET LOCAL session_replication_role = replica"))
                db.execute(
                    text(
                        "UPDATE financial_policy_versions SET rules = "
                        "rules || CAST(:change AS jsonb) WHERE version=:version"
                    ),
                    {
                        "change": json.dumps(rules),
                        "version": version,
                    },
                )
                db.execute(text("SET LOCAL session_replication_role = origin"))
                with pytest.raises(
                    DBAPIError, match="correction_approval_capture_invalid"
                ):
                    db.execute(query, {"id": approval_id})
            finally:
                transaction.rollback()
