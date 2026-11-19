"""Partner first-touch and working-manager assignments remain independent."""

import importlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from tests.postgres_financial.test_creator_social import (
    profile_values,
    seed_profile,
    seed_user,
)
from tests.postgres_financial.test_telegram_order_summary import (
    financial_pg_engine,
    intake_env,
    paid_order,
)
from ugc_bot.application.services.referral_service import ReferralService
from ugc_bot.container.creator_invite_factory import build_creator_invites
from ugc_bot.infrastructure.db.creator_invite_models import INVITES
from ugc_bot.infrastructure.db.invite_partner_models import PARTNERS
from ugc_bot.infrastructure.db.manager_application_models import APPLICATIONS
from ugc_bot.infrastructure.db.models import (
    BloggerProfileModel,
    FinancialMovementModel,
    ItemAssignmentModel,
    ManagerOrderModel,
    UserModel,
    UserReferralBindingModel,
    UserReferralPendingModel,
)
from ugc_bot.infrastructure.db.repositories.creator_invites import create_invite
from ugc_bot.infrastructure.db.repositories.identity_history import (
    SqlAlchemyCreatorIdentityHistoryRepository,
)
from ugc_bot.infrastructure.db.repositories.invite_partners import (
    attach_opened_partner,
    ensure_work_manager,
    lock_invite_people,
    save_partner,
)

__all__ = ["financial_pg_engine", "intake_env"]


def partner(db):
    identity = seed_user(db)
    db.get(UserModel, identity).referral_code = uuid4().hex[:12]
    db.flush()
    return identity


def work_manager(db, identity, at):
    db.execute(
        APPLICATIONS.insert().values(
            user_id=identity,
            state="approved",
            answers={},
            updated_at=at,
        )
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("same_person", [False, True])
async def test_manual_partner_does_not_assign_work_and_can_equal_work_manager(
    intake_env,
    same_person,
):
    env = intake_env
    _, oid, _, _, _ = await paid_order(env, interested_creators=0)
    at = datetime.now(timezone.utc)
    with Session(env["pg"]) as db, db.begin():
        from ugc_bot.infrastructure.db.models import OrderModel

        creator = seed_profile(db, stable_id=uuid4().hex)
        handle = f"u{creator.hex[:20]}"
        db.get(
            BloggerProfileModel, creator
        ).instagram_url = f"https://instagram.com/{handle}"
        db.flush()
        referrer = partner(db)
        manager = referrer if same_person else partner(db)
        work_manager(db, manager, at)
        before = db.scalar(select(func.clock_timestamp()))
        movements = db.scalar(
            select(func.count()).select_from(FinancialMovementModel)
        )
        lock_invite_people(db, handle, "", manager, referrer)
        ensure_work_manager(db, db.get(OrderModel, oid), manager, at)
        identity = create_invite(db, oid, None, manager, handle, at)
        save_partner(db, identity, referrer, at, "admin:test")
        assert (
            db.scalar(
                select(UserReferralBindingModel.referrer_user_id).where(
                    UserReferralBindingModel.referred_user_id == creator,
                )
            )
            == referrer
        )
        assert (
            db.scalar(
                select(INVITES.c.manager_id).where(INVITES.c.id == identity)
            )
            == manager
        )
        assert db.get(ManagerOrderModel, (manager, oid)) is not None
        if not same_person:
            assert db.get(ManagerOrderModel, (referrer, oid)) is None
        assert (
            db.scalar(select(func.count()).select_from(ItemAssignmentModel))
            == 0
        )
        assert (
            db.scalar(select(func.count()).select_from(FinancialMovementModel))
            == movements
        )
        assert db.scalar(select(PARTNERS.c.referrer_id)) == referrer
        migration = importlib.import_module(
            "ugc_bot.infrastructure.db.migrations.versions.0146_invite_partners"
        )
        with (
            pytest.raises(DBAPIError, match="invite_partner_history_exists"),
            db.begin_nested(),
            Operations.context(MigrationContext.configure(db.connection())),
        ):
            migration.downgrade()
        with (
            pytest.raises(
                DBAPIError, match="partner admin decisions are immutable"
            ),
            db.begin_nested(),
        ):
            db.execute(PARTNERS.update().values(created_by="changed"))
    history = SqlAlchemyCreatorIdentityHistoryRepository(
        env["container"].session_factory
    )
    assert (await history.read_direct_binding(creator, before)).binding is None
    with Session(env["pg"]) as db:
        after = db.scalar(select(func.clock_timestamp()))
    assert (
        await history.read_direct_binding(creator, after)
    ).binding.referrer_user_id == referrer


@pytest.mark.asyncio
@pytest.mark.parametrize("pending", [False, True])
async def test_existing_referrer_is_preserved_even_when_staff_selects_another(
    intake_env,
    pending,
):
    env = intake_env
    _, oid, _, _, _ = await paid_order(env, interested_creators=0)
    at = env["clock"].now()
    with Session(env["pg"]) as db, db.begin():
        creator = seed_profile(db, stable_id=uuid4().hex)
        handle = f"u{creator.hex[:20]}"
        db.get(
            BloggerProfileModel, creator
        ).instagram_url = f"https://instagram.com/{handle}"
        original, proposed = partner(db), partner(db)
        if pending:
            db.add(
                UserReferralPendingModel(
                    user_id=creator, referrer_user_id=original, created_at=at
                )
            )
        else:
            db.add(
                UserReferralBindingModel(
                    referred_user_id=creator,
                    referrer_user_id=original,
                    created_at=at,
                )
            )
        db.flush()
        identity = create_invite(db, oid, None, None, handle, at)
        save_partner(db, identity, proposed, at, "admin:test")
        save_partner(db, identity, proposed, at, "admin:test")
        assert (
            db.scalar(
                select(UserReferralBindingModel.referrer_user_id).where(
                    UserReferralBindingModel.referred_user_id == creator,
                )
            )
            == original
        )
        assert db.scalar(select(PARTNERS.c.referrer_id)) == original
        assert (
            db.scalar(
                select(UserReferralPendingModel).where(
                    UserReferralPendingModel.user_id == creator
                )
            )
            is None
        )
        assert db.get(ManagerOrderModel, (original, oid)) is None
        assert db.get(ManagerOrderModel, (proposed, oid)) is None


@pytest.mark.asyncio
async def test_external_invite_keeps_partner_through_normal_registration(
    intake_env,
):
    env = intake_env
    _, oid, _, _, _ = await paid_order(env, interested_creators=0)
    at = env["clock"].now()
    with Session(env["pg"]) as db, db.begin():
        referrer, other = partner(db), partner(db)
        creator = seed_user(db)
        identity = create_invite(
            db, oid, None, None, "external_partner_creator", at
        )
        save_partner(db, identity, referrer, at, "admin:test")
        # Reusing a staff-created link does not change its chosen partner.
        save_partner(db, identity, other, at, "admin:test")
    service = build_creator_invites(env["container"].transaction_manager)
    service.clock = env["clock"]
    await service.open_invite(identity, creator)
    with Session(env["pg"]) as db, db.begin():
        assert (
            db.scalar(
                select(UserReferralPendingModel.referrer_user_id).where(
                    UserReferralPendingModel.user_id == creator
                )
            )
            == referrer
        )
        values = profile_values(creator, stable_id=uuid4().hex)
        values.update(
            instagram_url="https://instagram.com/external_partner_creator",
            created_at=at + timedelta(seconds=1),
        )
        db.execute(BloggerProfileModel.__table__.insert().values(**values))
    repos = env["container"].build_repos()
    referral = ReferralService(
        repos["user_repo"],
        repos["user_referral_pending_repo"],
        repos["user_referral_binding_repo"],
        env["container"].transaction_manager,
        repos["blogger_repo"],
    )
    binding = await referral.create_binding_from_pending(creator)
    assert binding.referrer_user_id == referrer
    with Session(env["pg"]) as db:
        assert db.get(ManagerOrderModel, (referrer, oid)) is None
        assert (
            db.scalar(
                select(INVITES.c.manager_id).where(INVITES.c.id == identity)
            )
            is None
        )


@pytest.mark.asyncio
async def test_opening_link_preserves_an_earlier_pending_referral(intake_env):
    env = intake_env
    _, oid, _, _, _ = await paid_order(env, interested_creators=0)
    at = env["clock"].now()
    with Session(env["pg"]) as db, db.begin():
        original, selected = partner(db), partner(db)
        creator = seed_user(db)
        db.add(
            UserReferralPendingModel(
                user_id=creator, referrer_user_id=original, created_at=at
            )
        )
        db.flush()
        identity = create_invite(
            db, oid, None, None, "external_pending_creator", at
        )
        save_partner(db, identity, selected, at, "admin:test")
    service = build_creator_invites(env["container"].transaction_manager)
    service.clock = env["clock"]
    await service.open_invite(identity, creator)
    with Session(env["pg"]) as db:
        assert (
            db.scalar(
                select(UserReferralPendingModel.referrer_user_id).where(
                    UserReferralPendingModel.user_id == creator
                )
            )
            == original
        )


@pytest.mark.asyncio
async def test_concurrent_openings_keep_only_the_first_partner(intake_env):
    env = intake_env
    _, oid, _, _, _ = await paid_order(env, interested_creators=0)
    at = env["clock"].now()
    with Session(env["pg"]) as db, db.begin():
        creator = seed_user(db)
        partners = [partner(db), partner(db)]
        identities = [
            create_invite(db, oid, None, None, handle, at)
            for handle in ("first_partner_link", "second_partner_link")
        ]
        for identity, referrer in zip(identities, partners, strict=True):
            save_partner(db, identity, referrer, at, "admin:test")
    barrier = Barrier(2)

    def opened(identity):
        with Session(env["pg"]) as db, db.begin():
            barrier.wait(timeout=10)
            attach_opened_partner(db, identity, creator, at)

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(opened, identities))
    with Session(env["pg"]) as db:
        owners = db.scalars(
            select(UserReferralPendingModel.referrer_user_id).where(
                UserReferralPendingModel.user_id == creator,
            )
        ).all()
        assert len(owners) == 1 and owners[0] in partners


@pytest.mark.asyncio
async def test_registered_creator_requires_verified_invite_before_attachment(
    intake_env,
):
    env = intake_env
    _, oid, _, _, _ = await paid_order(env, interested_creators=0)
    at = env["clock"].now()
    with Session(env["pg"]) as db, db.begin():
        referrer = partner(db)
        identity = create_invite(
            db, oid, None, None, "late_registered_creator", at
        )
        save_partner(db, identity, referrer, at, "admin:test")
        creator = seed_profile(db, stable_id=uuid4().hex)
        db.get(
            BloggerProfileModel, creator
        ).instagram_url = "https://instagram.com/wrong_creator"
    service = build_creator_invites(env["container"].transaction_manager)
    service.clock = service.selection.clock = service.delivery.clock = env[
        "clock"
    ]
    await service.open_invite(identity, creator)
    with pytest.raises(ValueError, match="creator_invite_instagram_mismatch"):
        await service.accept(identity, creator)
    with Session(env["pg"]) as db, db.begin():
        assert (
            db.scalar(
                select(UserReferralBindingModel).where(
                    UserReferralBindingModel.referred_user_id == creator
                )
            )
            is None
        )
        db.get(
            BloggerProfileModel, creator
        ).instagram_url = "https://instagram.com/late_registered_creator"
    await service.accept(identity, creator)
    with Session(env["pg"]) as db:
        assert (
            db.scalar(
                select(UserReferralBindingModel.referrer_user_id).where(
                    UserReferralBindingModel.referred_user_id == creator
                )
            )
            == referrer
        )
        assert db.get(ManagerOrderModel, (referrer, oid)) is None


@pytest.mark.asyncio
async def test_new_reader_works_before_optional_partner_migration(intake_env):
    from ugc_bot.infrastructure.db.repositories.invite_partners import installed

    env = intake_env
    _, oid, _, _, _ = await paid_order(env, interested_creators=0)
    migration = importlib.import_module(
        "ugc_bot.infrastructure.db.migrations.versions.0146_invite_partners"
    )
    with (
        env["pg"].begin() as connection,
        Operations.context(MigrationContext.configure(connection)),
    ):
        migration.downgrade()
    with Session(env["pg"]) as db, db.begin():
        assert not installed(db)
        user_id = seed_user(db)
        identity = create_invite(
            db, oid, None, None, "old_schema_invite", env["clock"].now()
        )
        save_partner(db, identity, None, env["clock"].now(), "admin:test")
    service = build_creator_invites(env["container"].transaction_manager)
    service.clock = env["clock"]
    row = await service.open_invite(identity, user_id)
    assert row["id"] == identity


@pytest.mark.asyncio
async def test_cross_account_referrals_allow_foreign_key_checks(
    intake_env,
):
    env = intake_env
    _, oid, _, _, _ = await paid_order(env, interested_creators=0)
    at = env["clock"].now()
    with Session(env["pg"]) as db, db.begin():
        people = [partner(db), partner(db)]
        identities = [
            create_invite(db, oid, None, None, handle, at)
            for handle in ("cross_referral_first", "cross_referral_second")
        ]
        for identity, referrer in zip(
            identities, reversed(people), strict=True
        ):
            save_partner(db, identity, referrer, at, "admin:test")
    barrier = Barrier(2)

    def opened(index):
        with Session(env["pg"]) as db, db.begin():
            barrier.wait(timeout=10)
            attach_opened_partner(db, identities[index], people[index], at)

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(opened, [0, 1]))
    with Session(env["pg"]) as db:
        for user_id, owner in zip(people, reversed(people), strict=True):
            assert (
                db.scalar(
                    select(UserReferralPendingModel.referrer_user_id).where(
                        UserReferralPendingModel.user_id == user_id
                    )
                )
                == owner
            )
