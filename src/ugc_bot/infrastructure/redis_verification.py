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

_PREFIX = "ugc:ig_verify:"
_CODE_INDEX_PREFIX = "ugc:ig_verify_code:"
_USER_INDEX_PREFIX = "ugc:ig_verify_user:"


def _code_key(code_id: UUID) -> str:
    return f"{_PREFIX}{code_id}"


def _code_index_key(code: str) -> str:
    return f"{_CODE_INDEX_PREFIX}{code.upper()}"


def _user_index_key(user_id: UUID, code: str) -> str:
    return f"{_USER_INDEX_PREFIX}{user_id}:{code.upper()}"


def _serialize(vc: InstagramVerificationCode) -> str:
    return json.dumps(
        {
            "code_id": str(vc.code_id),
            "user_id": str(vc.user_id),
            "code": vc.code,
            "expires_at": vc.expires_at.isoformat(),
            "used": vc.used,
            "created_at": vc.created_at.isoformat(),
        }
    )


def _deserialize(data: str) -> InstagramVerificationCode:
    d = json.loads(data)
    return InstagramVerificationCode(
        code_id=UUID(d["code_id"]),
        user_id=UUID(d["user_id"]),
        code=d["code"],
        expires_at=datetime.fromisoformat(d["expires_at"]),
        used=d["used"],
        created_at=datetime.fromisoformat(d["created_at"]),
    )


class RedisInstagramVerificationRepository(InstagramVerificationRepository):
    """Redis-backed verification code storage with TTL-based expiry."""

    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url
        self._redis: "Redis | None" = None

    def _get_redis(self) -> "Redis":
        if self._redis is not None:
            return self._redis
        from redis.asyncio import Redis

        self._redis = Redis.from_url(self._redis_url, decode_responses=True)
        return self._redis

    async def save(
        self, code: InstagramVerificationCode, session: object | None = None
    ) -> None:
        redis = self._get_redis()
        now = datetime.now(timezone.utc)
        ttl_seconds = int((code.expires_at - now).total_seconds())
        if ttl_seconds <= 0:
            return

        payload = _serialize(code)
        pipe = redis.pipeline()
        pipe.setex(_code_key(code.code_id), ttl_seconds, payload)
        pipe.setex(_code_index_key(code.code), ttl_seconds, payload)
        pipe.setex(
            _user_index_key(code.user_id, code.code), ttl_seconds, payload
        )
        await pipe.execute()

    async def get_valid_code(
        self, user_id: UUID, code: str, session: object | None = None
    ) -> Optional[InstagramVerificationCode]:
        redis = self._get_redis()
        raw = await redis.get(_user_index_key(user_id, code))
        if raw is None:
            return None
        vc = _deserialize(raw)
        if vc.used:
            return None
        return vc

    async def get_valid_code_by_code(
        self, code: str, session: object | None = None
    ) -> Optional[InstagramVerificationCode]:
        redis = self._get_redis()
        raw = await redis.get(_code_index_key(code))
        if raw is None:
            return None
        vc = _deserialize(raw)
        if vc.used:
            return None
        return vc

    async def mark_used(
        self, code_id: UUID, session: object | None = None
    ) -> None:
        redis = self._get_redis()
        raw = await redis.get(_code_key(code_id))
        if raw is None:
            return
        vc = _deserialize(raw)
        used_vc = InstagramVerificationCode(
            code_id=vc.code_id,
            user_id=vc.user_id,
            code=vc.code,
            expires_at=vc.expires_at,
            used=True,
            created_at=vc.created_at,
        )
        ttl = await redis.ttl(_code_key(code_id))
        if ttl <= 0:
            ttl = 60
        payload = _serialize(used_vc)
        pipe = redis.pipeline()
        pipe.setex(_code_key(code_id), ttl, payload)
        pipe.setex(_code_index_key(vc.code), ttl, payload)
        pipe.setex(_user_index_key(vc.user_id, vc.code), ttl, payload)
        await pipe.execute()
