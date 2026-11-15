"""Write one durable application per Telegram account."""

import re
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert

from ugc_bot.domain.creator_invites import instagram_handle
from ugc_bot.domain.manager_application import FIELD_CHOICES, FIELDS
from ugc_bot.infrastructure.db.manager_application_models import APPLICATIONS
from ugc_bot.infrastructure.db.repositories.financial_items import _session
from ugc_bot.infrastructure.db.social_models import SocialAccountModel


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

    async def answer(self, user_id, field, value):
        now = datetime.now(timezone.utc)
        value = value.strip()
        if field not in FIELDS or not 0 < len(value) <= FIELDS[field][1]:
            raise ValueError("Проверьте длину ответа.")
        if field == "instagram":
            value = instagram_handle(value)
        if field in FIELD_CHOICES and value not in FIELD_CHOICES[field]:
            raise ValueError("Выберите один из предложенных вариантов.")
        if field == "phone" and not re.fullmatch(r"\+?[0-9]{7,15}", value):
            raise ValueError("Поделитесь своим номером через кнопку.")
        async with self.transactions.transaction() as session:
            db = _session(session)
            row = await self._row(db, user_id, lock=True)
            self._editable(row)
            values = dict(
                answers={**row["answers"], field: value}, updated_at=now
            )
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
            await db.execute(
                update(APPLICATIONS)
                .where(APPLICATIONS.c.user_id == user_id)
                .values(**values)
            )

    @staticmethod
    def _editable(row):
        if row["state"] not in {"draft", "clarify", "declined"}:
            raise ValueError("Заявка уже на рассмотрении или одобрена.")

    async def submit(self, user_id):
        now = datetime.now(timezone.utc)
        async with self.transactions.transaction() as session:
            db = _session(session)
            row = await self._row(db, user_id, lock=True)
            if row["state"] == "submitted":
                return
            self._editable(row)
            if not set(FIELDS) <= row["answers"].keys():
                raise ValueError("Заполните пропущенные ответы.")
            await db.execute(
                update(APPLICATIONS)
                .where(APPLICATIONS.c.user_id == user_id)
                .values(
                    state="submitted",
                    submitted_at=now,
                    updated_at=now,
                    decision_note=None,
                )
            )

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
            if current["challenge"] != code or current[
                "challenge_until"
            ] <= datetime.now(timezone.utc):
                return False
            await db.execute(
                update(APPLICATIONS)
                .where(APPLICATIONS.c.user_id == row.user_id)
                .values(
                    instagram_user_id=sender,
                    instagram_verified_at=datetime.now(timezone.utc),
                    challenge=None,
                    challenge_until=None,
                )
            )
            return True
