"""PostgreSQL review, membership, immutable history and authority."""

from uuid import uuid4

import pytest
from sqlalchemy import text, update
from sqlalchemy.exc import DBAPIError

from tests.helpers.factories import create_test_user
from tests.postgres_financial.test_order_intake import (
    command,
    intake_env,
    service,
)
from ugc_bot.application.native_principal_ports import (
    AuthenticatedMessengerPrincipal,
)
from ugc_bot.application.partner_admin_ports import (
    BindingCorrectionCommand,
    LeadReviewCommand,
)
from ugc_bot.application.services.partner_admin_service import (
    PartnerAdminService,
)
from ugc_bot.domain.entities import UserReferralBinding
from ugc_bot.infrastructure.db.models import UserModel
from ugc_bot.infrastructure.db.repositories.partner_admin import (
    SqlAlchemyPartnerAdminRepository,
)

__all__ = ["intake_env"]


def admin_service(env):
    return PartnerAdminService(SqlAlchemyPartnerAdminRepository(), env["clock"])


def principal(env):
    user = env["admin"]
    return AuthenticatedMessengerPrincipal(
        user.user_id, "telegram", user.telegram_id
    )


@pytest.mark.asyncio
async def test_accept_review_preserves_unpaid_lead_and_adds_no_money(
    intake_env,
):
    env = intake_env
    result = await service(env).create(
        command(env, service_mode="with_manager")
    )
    manager = await create_test_user(
        env["repos"]["user_repo"], external_id=str(uuid4())
    )
    app = admin_service(env)
    review = LeadReviewCommand(
        "review:" + str(result.lead_id),
        env["admin"].user_id,
        result.lead_id,
        0,
        "accept",
        (manager.user_id, env["admin"].user_id),
        "Approved manual accompaniment",
    )
    async with env["container"].transaction_manager.transaction() as db:
        accepted = await app.review_lead(
            review, principal=principal(env), session=db
        )
    async with env["container"].transaction_manager.transaction() as db:
        assert (
            await app.review_lead(review, principal=principal(env), session=db)
            == accepted
        )
        queue = await app.queue(
            env["admin"].user_id,
            principal=principal(env),
            status="accepted",
            session=db,
        )
        assert any(row["lead_id"] == result.lead_id for row in queue["entries"])
        assert (
            await db.scalar(
                text("SELECT state FROM accompaniment_leads WHERE lead_id=:id"),
                {"id": result.lead_id},
            )
            == "requested_unpaid"
        )
        assert (
            await db.scalar(
                text("SELECT count(*) FROM manager_orders WHERE order_id=:id"),
                {"id": result.order_id},
            )
            == 2
        )
        assert (
            await db.scalar(
                text(
                    "SELECT count(*) FROM financial_obligations WHERE "
                    "order_id=:id "
                ),
                {"id": result.order_id},
            )
            == 0
        )
        assert (
            await db.scalar(
                text(
                    "SELECT count(*) FROM accompaniment_lead_reviews "
                    "WHERE lead_id=:id "
                ),
                {"id": result.lead_id},
            )
            == 1
        )
    with pytest.raises(DBAPIError), env["pg"].begin() as connection:
        connection.execute(
            text(
                "UPDATE accompaniment_lead_reviews SET reason='changed' "
                "WHERE lead_id=:id "
            ),
            {"id": result.lead_id},
        )
    async with env["container"].transaction_manager.transaction() as db:
        await db.execute(
            update(UserModel)
            .where(UserModel.user_id == env["admin"].user_id)
            .values(admin=False)
        )
    with pytest.raises(ValueError, match="active_admin_required"):
        async with env["container"].transaction_manager.transaction() as db:
            await app.review_lead(review, principal=principal(env), session=db)


@pytest.mark.asyncio
async def test_correction_keeps_history_and_requires_current_proof(
    intake_env,
):
    env = intake_env
    partners = [
        await create_test_user(
            env["repos"]["user_repo"], external_id=str(uuid4())
        )
        for _ in range(2)
    ]
    old, new = [user.user_id for user in partners]
    referred = env["user"].user_id
    await env["repos"]["user_referral_binding_repo"].save(
        UserReferralBinding(old, referred, env["clock"].at)
    )
    with env["pg"].connect() as connection:
        original = connection.execute(
            text(
                "SELECT "
                "observation_sequence,referrer_user_id,active,created_at "
                "FROM creator_direct_binding_observations WHERE "
                "referred_user_id=:id ORDER BY observation_sequence "
            ),
            {"id": referred},
        ).all()
    repair = BindingCorrectionCommand(
        "repair:" + str(referred),
        env["admin"].user_id,
        referred,
        old,
        new,
        "Technical original attribution repair",
    )
    app = admin_service(env)
    async with env["container"].transaction_manager.transaction() as db:
        result = await app.correct_binding(
            repair, principal=principal(env), session=db
        )
    async with env["container"].transaction_manager.transaction() as db:
        assert (
            await app.correct_binding(
                repair, principal=principal(env), session=db
            )
            == result
        )
        assert (
            await db.scalar(
                text(
                    "SELECT referrer_user_id FROM "
                    "user_referral_bindings WHERE referred_user_id=:id "
                ),
                {"id": referred},
            )
            == new
        )
        audit = (
            (
                await db.execute(
                    text(
                        "SELECT * FROM referral_binding_corrections "
                        "WHERE referred_id=:id "
                    ),
                    {"id": referred},
                )
            )
            .mappings()
            .one()
        )
        assert (
            audit["actor_id"] == env["admin"].user_id
            and audit["reason"] == repair.reason
        )
        await db.execute(
            update(UserModel)
            .where(UserModel.user_id == env["admin"].user_id)
            .values(telegram_id="changed-native-owner")
        )
    with env["pg"].connect() as connection:
        preserved = connection.execute(
            text(
                "SELECT "
                "observation_sequence,referrer_user_id,active,created_at "
                "FROM creator_direct_binding_observations WHERE "
                "referred_user_id=:id AND observation_sequence<=:seq "
                "ORDER BY observation_sequence "
            ),
            {"id": referred, "seq": original[-1][0]},
        ).all()
        assert preserved == original
    with pytest.raises(ValueError, match="financial_principal_changed"):
        async with env["container"].transaction_manager.transaction() as db:
            await app.correct_binding(
                repair, principal=principal(env), session=db
            )
