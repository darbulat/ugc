"""SQLAlchemy repository implementations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from datetime import datetime, timezone

from ugc_bot.application.ports import (
    AdvertiserProfileRepository,
    BloggerProfileRepository,
    InstagramVerificationRepository,
    UserRepository,
)
from ugc_bot.domain.entities import (
    AdvertiserProfile,
    BloggerProfile,
    InstagramVerificationCode,
    User,
)
from ugc_bot.domain.enums import MessengerType
from ugc_bot.infrastructure.db.models import (
    AdvertiserProfileModel,
    BloggerProfileModel,
    InstagramVerificationCodeModel,
    UserModel,
)


@dataclass(slots=True)
class SqlAlchemyUserRepository(UserRepository):
    """SQLAlchemy-backed user repository."""

    session_factory: sessionmaker[Session]

    def get_by_id(self, user_id: UUID) -> Optional[User]:
        """Fetch a user by ID."""

        with self.session_factory() as session:
            result = session.execute(
                select(UserModel).where(UserModel.user_id == user_id)
            ).scalar_one_or_none()
            return _to_user_entity(result) if result else None

    def get_by_external(
        self, external_id: str, messenger_type: MessengerType
    ) -> Optional[User]:
        """Fetch a user by external messenger id."""

        with self.session_factory() as session:
            result = session.execute(
                select(UserModel).where(
                    UserModel.external_id == external_id,
                    UserModel.messenger_type == messenger_type.value,
                )
            ).scalar_one_or_none()
            return _to_user_entity(result) if result else None

    def save(self, user: User) -> None:
        """Persist a user."""

        with self.session_factory() as session:
            model = _to_user_model(user)
            session.merge(model)
            session.commit()


@dataclass(slots=True)
class SqlAlchemyBloggerProfileRepository(BloggerProfileRepository):
    """SQLAlchemy-backed blogger profile repository."""

    session_factory: sessionmaker[Session]

    def get_by_user_id(self, user_id: UUID) -> Optional[BloggerProfile]:
        """Fetch blogger profile by user id."""

        with self.session_factory() as session:
            result = session.execute(
                select(BloggerProfileModel).where(
                    BloggerProfileModel.user_id == user_id
                )
            ).scalar_one_or_none()
            return _to_blogger_profile_entity(result) if result else None

    def save(self, profile: BloggerProfile) -> None:
        """Persist blogger profile."""

        with self.session_factory() as session:
            model = _to_blogger_profile_model(profile)
            session.merge(model)
            session.commit()


@dataclass(slots=True)
class SqlAlchemyAdvertiserProfileRepository(AdvertiserProfileRepository):
    """SQLAlchemy-backed advertiser profile repository."""

    session_factory: sessionmaker[Session]

    def get_by_user_id(self, user_id: UUID) -> Optional[AdvertiserProfile]:
        """Fetch advertiser profile by user id."""

        with self.session_factory() as session:
            result = session.execute(
                select(AdvertiserProfileModel).where(
                    AdvertiserProfileModel.user_id == user_id
                )
            ).scalar_one_or_none()
            return _to_advertiser_profile_entity(result) if result else None

    def save(self, profile: AdvertiserProfile) -> None:
        """Persist advertiser profile."""

        with self.session_factory() as session:
            model = _to_advertiser_profile_model(profile)
            session.merge(model)
            session.commit()


@dataclass(slots=True)
class SqlAlchemyInstagramVerificationRepository(InstagramVerificationRepository):
    """SQLAlchemy-backed Instagram verification repository."""

    session_factory: sessionmaker[Session]

    def save(self, code: InstagramVerificationCode) -> None:
        """Persist verification code."""

        with self.session_factory() as session:
            model = _to_verification_model(code)
            session.merge(model)
            session.commit()

    def get_valid_code(
        self, user_id: UUID, code: str
    ) -> Optional[InstagramVerificationCode]:
        """Fetch a valid, unexpired verification code."""

        now = datetime.now(timezone.utc)
        with self.session_factory() as session:
            result = session.execute(
                select(InstagramVerificationCodeModel).where(
                    InstagramVerificationCodeModel.user_id == user_id,
                    InstagramVerificationCodeModel.code == code,
                    InstagramVerificationCodeModel.used.is_(False),
                    InstagramVerificationCodeModel.expires_at > now,
                )
            ).scalar_one_or_none()
            if result is None:
                return None
            if result.used or result.expires_at <= now:
                return None
            if result.code != code or result.user_id != user_id:
                return None
            return _to_verification_entity(result)

    def mark_used(self, code_id: UUID) -> None:
        """Mark verification code as used."""

        with self.session_factory() as session:
            model = session.get(InstagramVerificationCodeModel, code_id)
            if model is None:
                return
            model.used = True
            session.commit()


def _to_user_entity(model: UserModel) -> User:
    """Map user ORM model to domain entity."""

    return User(
        user_id=model.user_id,
        external_id=model.external_id,
        messenger_type=model.messenger_type,
        username=model.username,
        role=model.role,
        status=model.status,
        issue_count=model.issue_count,
        created_at=model.created_at,
    )


def _to_user_model(user: User) -> UserModel:
    """Map domain user entity to ORM model."""

    return UserModel(
        user_id=user.user_id,
        external_id=user.external_id,
        messenger_type=user.messenger_type,
        username=user.username,
        role=user.role,
        status=user.status,
        issue_count=user.issue_count,
        created_at=user.created_at,
    )


def _to_blogger_profile_entity(
    model: BloggerProfileModel,
) -> BloggerProfile:
    """Map blogger profile ORM model to domain entity."""

    return BloggerProfile(
        user_id=model.user_id,
        instagram_url=model.instagram_url,
        confirmed=model.confirmed,
        topics=model.topics,
        audience_gender=model.audience_gender,
        audience_age_min=model.audience_age_min,
        audience_age_max=model.audience_age_max,
        audience_geo=model.audience_geo,
        price=float(model.price),
        updated_at=model.updated_at,
    )


def _to_blogger_profile_model(
    profile: BloggerProfile,
) -> BloggerProfileModel:
    """Map domain blogger profile entity to ORM model."""

    return BloggerProfileModel(
        user_id=profile.user_id,
        instagram_url=profile.instagram_url,
        confirmed=profile.confirmed,
        topics=profile.topics,
        audience_gender=profile.audience_gender,
        audience_age_min=profile.audience_age_min,
        audience_age_max=profile.audience_age_max,
        audience_geo=profile.audience_geo,
        price=profile.price,
        updated_at=profile.updated_at,
    )


def _to_advertiser_profile_entity(
    model: AdvertiserProfileModel,
) -> AdvertiserProfile:
    """Map advertiser profile ORM model to domain entity."""

    return AdvertiserProfile(user_id=model.user_id, contact=model.contact)


def _to_advertiser_profile_model(
    profile: AdvertiserProfile,
) -> AdvertiserProfileModel:
    """Map domain advertiser profile entity to ORM model."""

    return AdvertiserProfileModel(
        user_id=profile.user_id,
        contact=profile.contact,
    )


def _to_verification_entity(
    model: InstagramVerificationCodeModel,
) -> InstagramVerificationCode:
    """Map verification ORM model to domain entity."""

    return InstagramVerificationCode(
        code_id=model.code_id,
        user_id=model.user_id,
        code=model.code,
        expires_at=model.expires_at,
        used=model.used,
        created_at=model.created_at,
    )


def _to_verification_model(
    code: InstagramVerificationCode,
) -> InstagramVerificationCodeModel:
    """Map domain verification entity to ORM model."""

    return InstagramVerificationCodeModel(
        code_id=code.code_id,
        user_id=code.user_id,
        code=code.code,
        expires_at=code.expires_at,
        used=code.used,
        created_at=code.created_at,
    )
