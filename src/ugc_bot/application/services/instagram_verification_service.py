"""Service for Instagram verification."""

from __future__ import annotations

import secrets
import string
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from ugc_bot.application.errors import BloggerRegistrationError, UserNotFoundError
from ugc_bot.application.ports import (
    BloggerProfileRepository,
    InstagramVerificationRepository,
    UserRepository,
)
from ugc_bot.domain.entities import InstagramVerificationCode


@dataclass(slots=True)
class InstagramVerificationService:
    """Generate and verify Instagram confirmation codes."""

    user_repo: UserRepository
    blogger_repo: BloggerProfileRepository
    verification_repo: InstagramVerificationRepository

    def generate_code(self, user_id: UUID) -> InstagramVerificationCode:
        """Generate and store a new verification code."""

        if self.user_repo.get_by_id(user_id) is None:
            raise UserNotFoundError("User not found for Instagram verification.")

        code = _generate_code()
        now = datetime.now(timezone.utc)
        verification = InstagramVerificationCode(
            code_id=uuid4(),
            user_id=user_id,
            code=code,
            expires_at=now + timedelta(minutes=15),
            used=False,
            created_at=now,
        )
        self.verification_repo.save(verification)
        return verification

    def verify_code(self, user_id: UUID, code: str) -> bool:
        """Validate code and confirm blogger profile."""

        profile = self.blogger_repo.get_by_user_id(user_id)
        if profile is None:
            raise BloggerRegistrationError("Blogger profile not found.")

        valid_code = self.verification_repo.get_valid_code(
            user_id, code.strip().upper()
        )
        if valid_code is None:
            return False

        self.verification_repo.mark_used(valid_code.code_id)
        confirmed_profile = profile.__class__(
            user_id=profile.user_id,
            instagram_url=profile.instagram_url,
            confirmed=True,
            topics=profile.topics,
            audience_gender=profile.audience_gender,
            audience_age_min=profile.audience_age_min,
            audience_age_max=profile.audience_age_max,
            audience_geo=profile.audience_geo,
            price=profile.price,
            updated_at=datetime.now(timezone.utc),
        )
        self.blogger_repo.save(confirmed_profile)
        return True


def _generate_code(length: int = 8) -> str:
    """Generate a random verification code."""

    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))
