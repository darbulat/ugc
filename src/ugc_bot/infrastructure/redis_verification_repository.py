"""Redis-backed Instagram verification code repository."""

import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional
from uuid import UUID

from ugc_bot.application.ports import InstagramVerificationRepository
from ugc_bot.domain.entities import InstagramVerificationCode

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)

_CODE_KEY = "ig_verify:code:{code}"
_USER_KEY = "ig_verify:user:{user_id}:{code}"
_ID_KEY = "ig_verify:id:{code_id}"
_TTL_SECONDS = 900  # 15 minutes


def _serialize(code: InstagramVerificationCode) -> str:
    return json.dumps(
        {
            "code_id": str(code.code_id),
            "user_id": str(code.user_id),
            "code": code.code,
            "expires_at": code.expires_at.isoformat(),
            "used": code.used,
            "created_at": code.created_at.isoformat(),
        }
    )


def _deserialize(raw: str) -> InstagramVerificationCode:
    data = json.loads(raw)
    return InstagramVerificationCode(
        code_id=UUID(data["code_id"]),
        user_id=UUID(data["user_id"]),
        code=data["code"],
        expires_at=datetime.fromisoformat(data["expires_at"]),
        used=data["used"],
        created_at=datetime.fromisoformat(data["created_at"]),
    )


def _is_valid(code: InstagramVerificationCode) -> bool:
    """Check code is not used and not expired."""
    return not code.used and code.expires_at > datetime.now(timezone.utc)


class RedisInstagramVerificationRepository(InstagramVerificationRepository):
    """Redis-backed Instagram verification repository with auto-TTL."""

    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url
        self._redis: "Redis | None" = None

    def _get_redis(self) -> "Redis":
        if self._redis is not None:
            return self._redis
        from redis.asyncio import Redis  # pragma: no cover

        self._redis = Redis.from_url(  # pragma: no cover
            self._redis_url,
            decode_responses=True,
            max_connections=10,
            socket_timeout=5.0,
            socket_connect_timeout=5.0,
        )
        return self._redis  # pragma: no cover

    async def save(
        self, code: InstagramVerificationCode, session: object | None = None
    ) -> None:
        """Persist verification code with TTL."""
        redis = self._get_redis()
        payload = _serialize(code)
        id_payload = json.dumps(
            {"code": code.code, "user_id": str(code.user_id)}
        )
        pipe = redis.pipeline()
        pipe.setex(_CODE_KEY.format(code=code.code), _TTL_SECONDS, payload)
        pipe.setex(
            _USER_KEY.format(user_id=code.user_id, code=code.code),
            _TTL_SECONDS,
            payload,
        )
        pipe.setex(
            _ID_KEY.format(code_id=code.code_id), _TTL_SECONDS, id_payload
        )
        await pipe.execute()

    async def get_valid_code(
        self, user_id: UUID, code: str, session: object | None = None
    ) -> Optional[InstagramVerificationCode]:
        """Fetch a valid, unexpired verification code."""
        redis = self._get_redis()
        raw = await redis.get(_USER_KEY.format(user_id=user_id, code=code))
        if raw is None:
            return None
        entity = _deserialize(raw)
        return entity if _is_valid(entity) else None

    async def get_valid_code_by_code(
        self, code: str, session: object | None = None
    ) -> Optional[InstagramVerificationCode]:
        """Fetch valid unexpired verification code by string."""
        redis = self._get_redis()
        raw = await redis.get(_CODE_KEY.format(code=code))
        if raw is None:
            return None
        entity = _deserialize(raw)
        return entity if _is_valid(entity) else None

    async def mark_used(
        self, code_id: UUID, session: object | None = None
    ) -> None:
        """Mark verification code as used by deleting all keys."""
        redis = self._get_redis()
        raw = await redis.get(_ID_KEY.format(code_id=code_id))
        if raw is None:
            return
        data = json.loads(raw)
        code = data["code"]
        user_id = data["user_id"]
        pipe = redis.pipeline()
        pipe.delete(_CODE_KEY.format(code=code))
        pipe.delete(_USER_KEY.format(user_id=user_id, code=code))
        pipe.delete(_ID_KEY.format(code_id=code_id))
        await pipe.execute()
