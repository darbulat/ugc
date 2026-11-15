"""Write one durable application per Telegram account."""

import re
import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert

from ugc_bot.domain.manager_application import (
    MANAGER_APPROVED,
    MANAGER_INSTAGRAM_VERIFIED,
    MANAGER_READY_FOR_REVIEW,
    MANAGER_REVIEWABLE_STATES,
    MANAGER_REVIEWERS,
    MANAGER_SUBMITTED,
    application_fields,
    application_version,
    missing_application_fields,
    validate_application_answer,
)
from ugc_bot.infrastructure.db.manager_application_models import APPLICATIONS
from ugc_bot.infrastructure.db.models import (
    AuditLogModel,
    OutboxEventModel,
    UserModel,
)
from ugc_bot.infrastructure.db.repositories.financial_items import _session
from ugc_bot.infrastructure.db.social_models import SocialAccountModel


def _enqueue_notice(db, user_id, event_type, at, payload):
    db.add(
        OutboxEventModel(
            event_id=uuid4(),
            aggregate_id=str(user_id),
            aggregate_type="manager_application",
            event_type=event_type,
            created_at=at,
            payload=payload,
        )
    )


def record_manager_review(db, user_id, state, source, at, actor_id=None):
    values = {"state": state, "source": source}
    if actor_id:
        values["actor_id"] = str(actor_id)
    db.add(
        AuditLogModel(
            entity_type="manager_application",
            entity_id=user_id,
            action="update",
            new_values=values,
            changed_at=at,
        )
    )
    if state == "approved":
        _enqueue_notice(db, user_id, MANAGER_APPROVED, at, {})


def review_manager_application(
    db, user_id, command, note, *, version=None, actor_id=None
):
    candidate = (
        db.execute(
            select(APPLICATIONS)
            .where(APPLICATIONS.c.user_id == user_id)
            .with_for_update()
        )
        .mappings()
        .one_or_none()
    )
    if candidate is None or candidate["state"] not in MANAGER_REVIEWABLE_STATES:
        raise ValueError("Заявка уже обработана.")
    if version is not None and version != application_version(
        candidate["submitted_at"]
    ):
        raise ValueError("Анкета обновилась. Откройте её заново.")
    if command == "approved" and not candidate["instagram_verified_at"]:
        raise ValueError("Кандидату нужно подтвердить Instagram.")
    if command == "clarify" and not (note or candidate["decision_note"]):
        raise ValueError("Напишите во внутренней заметке, что нужно уточнить.")
    now = datetime.now(timezone.utc)
    if command == "note":
        state = candidate["state"]
        values = dict(updated_at=now, decision_note=note or None)
    else:
        state = command
        values = dict(
            state=state,
            reviewed_at=now,
            updated_at=now,
            decision_note=note or candidate["decision_note"],
        )
    db.execute(
        update(APPLICATIONS)
        .where(APPLICATIONS.c.user_id == user_id)
        .values(**values)
    )
    record_manager_review(db, user_id, state, command, now, actor_id)


def manager_application_query(user_id):
    return (
        select(
            APPLICATIONS,
            UserModel.telegram,
            UserModel.telegram_id,
            UserModel.username,
        )
        .join(UserModel, UserModel.user_id == APPLICATIONS.c.user_id)
        .where(APPLICATIONS.c.user_id == user_id)
    )


class ManagerApplications:
    def __init__(self, transactions, instagram_api):
        self.transactions = transactions
        self.instagram_api = instagram_api

    async def approved(self, user_id):
        async with self.transactions.transaction() as session:
            db = _session(session)
            if not await db.scalar(select(func.to_regclass(APPLICATIONS.name))):
                return False
            return (
                await db.scalar(
                    select(APPLICATIONS.c.state).where(
                        APPLICATIONS.c.user_id == user_id
                    )
                )
            ) == "approved"

    async def open(self, user_id):
        async with self.transactions.transaction() as session:
            db = _session(session)
            await db.execute(
                insert(APPLICATIONS)
                .values(
                    user_id=user_id,
                    state="draft",
                    answers={},
                    updated_at=datetime.now(timezone.utc),
                )
                .on_conflict_do_nothing(index_elements=[APPLICATIONS.c.user_id])
            )
            return await self._row(db, user_id)

    @staticmethod
    async def _row(db, user_id, *, lock=False):
        query = select(APPLICATIONS).where(APPLICATIONS.c.user_id == user_id)
        return (
            (await db.execute(query.with_for_update() if lock else query))
            .mappings()
            .one()
        )

    async def answer(self, user_id, field, value, *, location_context=None):
        now = datetime.now(timezone.utc)
        value = validate_application_answer(field, value)
        if field == "location" and (
            not location_context or not location_context[1]
        ):
            raise ValueError("Выберите город из найденного варианта.")
        async with self.transactions.transaction() as session:
            db = _session(session)
            row = await self._row(db, user_id, lock=True)
            self._editable(row)
            if field != "coverage" and field not in application_fields(
                row["answers"]
            ):
                raise ValueError("Этот вопрос больше не относится к анкете.")
            answers = {**row["answers"], field: value}
            if field == "work_format" and value != "Другое":
                answers.pop("work_format_details", None)
            if field == "location":
                region, country = location_context
                answers.update(
                    location_region=region or "", location_country=country
                )
            values = dict(answers=answers, updated_at=now)
            if field == "instagram" and value != row["instagram"]:
                proof = await db.scalar(
                    select(SocialAccountModel.external_id).where(
                        SocialAccountModel.user_id == user_id,
                        SocialAccountModel.platform == "instagram",
                        SocialAccountModel.handle == value,
                        SocialAccountModel.verified.is_(True),
                        SocialAccountModel.verification_source
                        == "instagram_webhook",
                    )
                )
                values.update(
                    instagram=value,
                    instagram_user_id=proof,
                    instagram_verified_at=now if proof else None,
                    challenge=None,
                    challenge_until=None,
                )
            if field != "coverage" and not missing_application_fields(answers):
                values.update(
                    state="submitted",
                    submitted_at=now,
                )
                for reviewer in MANAGER_REVIEWERS:
                    _enqueue_notice(
                        db,
                        user_id,
                        MANAGER_SUBMITTED,
                        now,
                        {
                            "reviewer": reviewer,
                            "submission": application_version(now),
                        },
                    )
            result = await db.execute(
                update(APPLICATIONS)
                .where(APPLICATIONS.c.user_id == user_id)
                .values(**values)
                .returning(*APPLICATIONS.c)
            )
            return result.mappings().one()

    async def review_card(self, user_id):
        async with self.transactions.transaction() as session:
            result = await _session(session).execute(
                manager_application_query(user_id).where(
                    APPLICATIONS.c.state != "draft"
                )
            )
            return result.mappings().one_or_none()

    async def approve_in_telegram(self, user_id: UUID, actor_id: UUID, version):
        async with self.transactions.transaction() as session:
            db = _session(session)
            authorized = await db.scalar(
                select(UserModel.user_id).where(
                    UserModel.user_id == actor_id,
                    UserModel.admin.is_(True),
                    UserModel.status == "active",
                )
            )
            if not authorized:
                raise ValueError("Действие доступно администраторам.")
            await db.run_sync(
                review_manager_application,
                user_id,
                "approved",
                "",
                version=version,
                actor_id=actor_id,
            )

    @staticmethod
    def _editable(row):
        if row["state"] not in {"draft", "clarify", "declined"}:
            raise ValueError("Заявка уже на рассмотрении или одобрена.")

    async def instagram_challenge(self, user_id):
        now = datetime.now(timezone.utc)
        async with self.transactions.transaction() as session:
            db = _session(session)
            row = await self._row(db, user_id, lock=True)
            if not row["instagram"] or row["instagram_verified_at"]:
                return None
            if row["challenge_until"] and row["challenge_until"] > now:
                return row["challenge"]
            code = "UMCM-" + secrets.token_hex(6).upper()
            await db.execute(
                update(APPLICATIONS)
                .where(APPLICATIONS.c.user_id == user_id)
                .values(
                    challenge=code,
                    challenge_until=now + timedelta(minutes=15),
                )
            )
            return code

    async def verify_instagram(self, code, sender):
        """Only a signed Meta event with a matching Graph username is proof."""
        if (
            not re.fullmatch(r"UMCM-[0-9A-F]{12}", code)
            or self.instagram_api is None
        ):
            return False
        now = datetime.now(timezone.utc)
        async with self.transactions.transaction() as session:
            db = _session(session)
            row = (
                await db.execute(
                    select(
                        APPLICATIONS.c.user_id, APPLICATIONS.c.instagram
                    ).where(
                        APPLICATIONS.c.challenge == code,
                        APPLICATIONS.c.challenge_until > now,
                    )
                )
            ).one_or_none()
        if row is None:
            return False
        profile = await self.instagram_api.get_profile_by_id(sender)
        if (
            profile is None
            or not profile.username
            or profile.username.casefold() != row.instagram
        ):
            return False
        async with self.transactions.transaction() as session:
            db = _session(session)
            await db.execute(
                text(
                    "SELECT pg_advisory_xact_lock("
                    "hashtextextended(:sender, 5201))"
                ),
                {"sender": str(sender)},
            )
            if await db.scalar(
                select(APPLICATIONS.c.user_id).where(
                    APPLICATIONS.c.instagram_user_id == sender,
                    APPLICATIONS.c.user_id != row.user_id,
                )
            ):
                return False
            current = await self._row(db, row.user_id, lock=True)
            verified_at = datetime.now(timezone.utc)
            if (
                current["challenge"] != code
                or current["challenge_until"] <= verified_at
            ):
                return False
            await db.execute(
                update(APPLICATIONS)
                .where(APPLICATIONS.c.user_id == row.user_id)
                .values(
                    instagram_user_id=sender,
                    instagram_verified_at=verified_at,
                    challenge=None,
                    challenge_until=None,
                )
            )
            if current["state"] in {*MANAGER_REVIEWABLE_STATES, "draft"}:
                _enqueue_notice(
                    db,
                    row.user_id,
                    MANAGER_INSTAGRAM_VERIFIED,
                    verified_at,
                    {"verification": application_version(verified_at)},
                )
            if current["state"] in MANAGER_REVIEWABLE_STATES:
                _enqueue_notice(
                    db,
                    row.user_id,
                    MANAGER_READY_FOR_REVIEW,
                    verified_at,
                    {
                        "submission": application_version(
                            current["submitted_at"]
                        )
                    },
                )
            return True
