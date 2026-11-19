"""First-touch partner attachment; never creates work assignments or income."""

from sqlalchemy import delete, exists, func, select
from sqlalchemy.dialects.postgresql import insert

from ugc_bot.domain.creator_invites import instagram_handle
from ugc_bot.infrastructure.db.creator_invite_models import INVITES
from ugc_bot.infrastructure.db.invite_partner_models import PARTNERS
from ugc_bot.infrastructure.db.manager_application_models import APPLICATIONS
from ugc_bot.infrastructure.db.models import (
    BloggerProfileModel,
    ManagerOrderModel,
    UserModel,
    UserReferralBindingModel,
    UserReferralPendingModel,
)


def installed(db):
    return db.get_bind().dialect.name == "postgresql" and bool(
        db.scalar(select(func.to_regclass(PARTNERS.name)))
    )


def admin_managers(order):
    return (
        select(UserModel.user_id, UserModel.username, UserModel.telegram)
        .where(
            UserModel.status == "active",
            UserModel.user_id != order.advertiser_id,
            exists().where(ManagerOrderModel.user_id == UserModel.user_id)
            | exists().where(
                APPLICATIONS.c.user_id == UserModel.user_id,
                APPLICATIONS.c.state == "approved",
            ),
        )
        .order_by(UserModel.username, UserModel.user_id)
    )


def ensure_work_manager(db, order, manager_id, at):
    if manager_id is None:
        return
    if not db.scalar(
        admin_managers(order).where(UserModel.user_id == manager_id)
    ):
        raise ValueError("creator_invite_manager_unavailable")
    db.execute(
        insert(ManagerOrderModel)
        .values(
            user_id=manager_id,
            order_id=order.order_id,
            created_at=at,
        )
        .on_conflict_do_nothing()
    )


def lock_invite_people(db, instagram, telegram, manager_id, referrer_id):
    """Take User locks before create_invite takes the shared order lock."""
    from ugc_bot.infrastructure.db.repositories.creator_invites import (
        matching_creator_profiles,
    )

    targets = matching_creator_profiles(db, instagram, telegram)
    target = next(iter(targets), None)
    current = existing_referrer(db, target)
    users = {
        value for value in (target, current, manager_id, referrer_id) if value
    }
    list(
        db.scalars(
            select(UserModel.user_id)
            .where(UserModel.user_id.in_(users))
            .order_by(UserModel.user_id)
            .with_for_update(key_share=True)
        )
    )
    if current != existing_referrer(db, target):
        raise ValueError("creator_invite_profile_conflict")


def existing_referrer(db, user_id):
    if user_id is None:
        return None
    binding = db.scalar(
        select(UserReferralBindingModel.referrer_user_id).where(
            UserReferralBindingModel.referred_user_id == user_id,
        )
    )
    return binding or db.scalar(
        select(UserReferralPendingModel.referrer_user_id)
        .where(
            UserReferralPendingModel.user_id == user_id,
        )
        .order_by(
            UserReferralPendingModel.created_at,
            UserReferralPendingModel.referrer_user_id,
        )
        .limit(1)
    )


def referrer_choices():
    return (
        select(UserModel.user_id, UserModel.username, UserModel.telegram)
        .where(
            UserModel.status == "active",
            UserModel.referral_code.is_not(None),
        )
        .order_by(UserModel.username, UserModel.user_id)
    )


def _attach(db, user_id, referrer_id, at, *, registered):
    # Match native registration's NO KEY UPDATE lock: serialize attribution
    # while allowing the other account's foreign-key references to proceed.
    user = db.get(UserModel, user_id, with_for_update={"key_share": True})
    if user is None or user_id == referrer_id:
        raise ValueError("creator_invite_referrer_invalid")
    current = db.scalar(
        select(UserReferralBindingModel.referrer_user_id).where(
            UserReferralBindingModel.referred_user_id == user_id,
        )
    )
    if current:
        return current
    pending = db.scalar(
        select(UserReferralPendingModel.referrer_user_id)
        .where(
            UserReferralPendingModel.user_id == user_id,
        )
        .order_by(
            UserReferralPendingModel.created_at,
            UserReferralPendingModel.referrer_user_id,
        )
        .limit(1)
    )
    referrer_id = pending or referrer_id
    profile = db.get(BloggerProfileModel, user_id)
    table = (
        UserReferralBindingModel
        if profile and registered
        else UserReferralPendingModel
    )
    if profile is not None and not registered:
        return None
    values = {"referrer_user_id": referrer_id, "created_at": at}
    values[
        "referred_user_id" if table is UserReferralBindingModel else "user_id"
    ] = user_id
    db.execute(insert(table).values(**values).on_conflict_do_nothing())
    if table is UserReferralBindingModel:
        db.execute(
            delete(UserReferralPendingModel).where(
                UserReferralPendingModel.user_id == user_id
            )
        )
    return existing_referrer(db, user_id)


def save_partner(db, identity, referrer_id, at, operator):
    """Called only by authenticated admin, inside the invite savepoint."""
    if not installed(db):
        if referrer_id:
            raise ValueError("creator_invite_partner_unavailable")
        return
    invite = (
        db.execute(select(INVITES).where(INVITES.c.id == identity))
        .mappings()
        .one()
    )
    target = invite["target_id"]
    current = existing_referrer(db, target)
    saved = db.scalar(
        select(PARTNERS.c.referrer_id).where(PARTNERS.c.invite_id == identity)
    )
    if not referrer_id and not current and not saved:
        return
    chosen = current or saved or referrer_id
    if chosen == target:
        raise ValueError("creator_invite_referrer_invalid")
    if (
        not current
        and not saved
        and not db.scalar(referrer_choices().where(UserModel.user_id == chosen))
    ):
        raise ValueError("creator_invite_referrer_invalid")
    if target:
        chosen = _attach(db, target, chosen, at, registered=True)
    db.execute(
        insert(PARTNERS)
        .values(
            invite_id=identity,
            referrer_id=chosen,
            created_at=at,
            created_by=operator,
        )
        .on_conflict_do_nothing()
    )


def attach_opened_partner(db, identity, user_id, at, *, confirmed=False):
    if user_id is None or not installed(db):
        return
    referrer = db.scalar(
        select(PARTNERS.c.referrer_id).where(PARTNERS.c.invite_id == identity)
    )
    if referrer is None or referrer == user_id:
        return
    invite = (
        db.execute(select(INVITES).where(INVITES.c.id == identity))
        .mappings()
        .one()
    )
    if confirmed:
        profile = db.get(BloggerProfileModel, user_id)
        if (
            not profile
            or not profile.confirmed
            or not profile.instagram_user_id
        ):
            return
        if instagram_handle(profile.instagram_url) != invite["instagram"]:
            return
    _attach(db, user_id, referrer, at, registered=confirmed)


def profile_referrer(db, order_id, instagram, telegram):
    from ugc_bot.infrastructure.db.repositories.creator_invites import (
        matching_creator_profiles,
    )

    try:
        matches = matching_creator_profiles(db, instagram, telegram)
        current = existing_referrer(db, next(iter(matches), None))
        if current is None and installed(db):
            current = db.scalar(
                select(PARTNERS.c.referrer_id)
                .join(INVITES, INVITES.c.id == PARTNERS.c.invite_id)
                .where(
                    INVITES.c.order_id == order_id,
                    INVITES.c.instagram == instagram_handle(instagram),
                )
                .order_by(PARTNERS.c.created_at)
                .limit(1)
            )
        if current is None:
            return None
        return (
            db.execute(
                select(
                    UserModel.user_id, UserModel.username, UserModel.telegram
                ).where(UserModel.user_id == current)
            )
            .mappings()
            .one_or_none()
        )
    except ValueError:
        return None
