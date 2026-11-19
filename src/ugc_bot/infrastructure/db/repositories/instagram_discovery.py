"""Independent metrics cache. No canonical identity or notification writes."""

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert

from ugc_bot.domain.instagram_discovery import (
    MOSCOW,
    DiscoveryResult,
    DiscoveryTarget,
    discovery_window,
    next_discovery_run,
)
from ugc_bot.infrastructure.db.instagram_discovery_models import (
    DISCOVERY as D,
)
from ugc_bot.infrastructure.db.instagram_discovery_models import (
    DISCOVERY_CONTROL as C,
)
from ugc_bot.infrastructure.db.instagram_maintenance_models import HEALTH as H
from ugc_bot.infrastructure.db.models import BloggerProfileModel, UserModel

P = BloggerProfileModel.__table__
REFRESH = timedelta(days=14)
LEASE = timedelta(seconds=120)


class DiscoveryRepository:
    def __init__(self, sessions, identity_context: str):
        if not identity_context.strip():
            raise ValueError("Explicit verification identity context required")
        self.sessions = sessions
        self.identity_context = identity_context

    async def claim(self, at: datetime) -> UUID | None:
        """New workers record a future slot, never run at boot."""
        async with self.sessions.begin() as db:
            await db.execute(
                insert(C)
                .values(singleton=1, next_run_at=next_discovery_run(at))
                .on_conflict_do_nothing()
            )
            row = (
                (await db.execute(sa.select(C).with_for_update()))
                .mappings()
                .one()
            )
            if (
                row["next_run_at"] > at
                or not discovery_window(at)
                or (row["lease_until"] and row["lease_until"] > at)
            ):
                return None
            lease = uuid4()
            await db.execute(
                sa.update(C).values(
                    lease_id=lease,
                    lease_until=at + LEASE,
                    next_run_at=next_discovery_run(at),
                    last_outcome="running",
                )
            )
            return lease

    def _eligible(self, at: datetime):
        return sa.and_(
            P.c.confirmed.is_(True),
            P.c.instagram_user_id.is_not(None),
            H.c.meta_id == P.c.instagram_user_id,
            H.c.identity_context == self.identity_context,
            H.c.status == "healthy",
            H.c.last_success_at >= at - timedelta(hours=48),
            sa.func.lower(P.c.instagram_username) == sa.func.lower(H.c.handle),
            H.c.handle.op("~")(r"^[A-Za-z0-9_.]{1,30}$"),
        )

    async def prepare(
        self, lease: UUID, at: datetime
    ) -> DiscoveryTarget | None:
        """Reserve budget before HTTP, including unsuccessful or lost calls."""
        async with self.sessions.begin() as db:
            control = (
                (await db.execute(sa.select(C).with_for_update()))
                .mappings()
                .one()
            )
            day = at.astimezone(MOSCOW).date()
            used = (
                control["requests_used"] if control["budget_day"] == day else 0
            )
            if (
                control["lease_id"] != lease
                or control["lease_until"] <= at
                or not discovery_window(at)
                or used >= 150
            ):
                return None
            row = (
                (
                    await db.execute(
                        sa.select(
                            P.c.user_id,
                            P.c.instagram_user_id,
                            P.c.instagram_url,
                            H.c.handle,
                        )
                        .join(H, H.c.user_id == P.c.user_id)
                        .outerjoin(D, D.c.user_id == P.c.user_id)
                        .where(
                            self._eligible(at),
                            sa.or_(
                                D.c.user_id.is_(None),
                                D.c.next_attempt_at <= at,
                                D.c.attempt_meta_id != P.c.instagram_user_id,
                                D.c.attempt_profile_url != P.c.instagram_url,
                            ),
                        )
                        .order_by(
                            D.c.next_attempt_at.asc().nullsfirst(),
                            H.c.last_success_at,
                            P.c.user_id,
                        )
                        .limit(1)
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                return None
            attempt = uuid4()
            values = dict(
                user_id=row["user_id"],
                attempt_meta_id=row["instagram_user_id"],
                attempt_profile_url=row["instagram_url"],
                attempt_id=attempt,
                attempted_at=at,
                next_attempt_at=at + REFRESH,
                last_outcome="reserved",
            )
            await db.execute(
                insert(D)
                .values(**values)
                .on_conflict_do_update(
                    index_elements=[D.c.user_id],
                    set_={k: v for k, v in values.items() if k != "user_id"},
                )
            )
            await db.execute(
                sa.update(C).values(
                    budget_day=day,
                    requests_used=used + 1,
                    lease_until=at + LEASE,
                )
            )
            return DiscoveryTarget(
                row["user_id"],
                row["instagram_user_id"],
                self.identity_context,
                row["handle"],
                row["instagram_url"],
                attempt,
            )

    async def finish(
        self,
        target: DiscoveryTarget,
        result: DiscoveryResult,
        context: str,
        at: datetime,
    ) -> str:
        async with self.sessions.begin() as db:
            # Follow the same ownership writer lock order as verification.
            await db.scalar(
                sa.select(UserModel.user_id)
                .where(UserModel.user_id == target.user_id)
                .with_for_update(key_share=True)
            )
            current = (
                await db.execute(
                    sa.select(P.c.user_id)
                    .join(H, H.c.user_id == P.c.user_id)
                    .where(
                        P.c.user_id == target.user_id,
                        self._eligible(at),
                        P.c.instagram_user_id == target.meta_id,
                        P.c.instagram_url == target.profile_url,
                        sa.func.lower(H.c.handle) == target.username.lower(),
                    )
                    .with_for_update(of=H)
                )
            ).first()
            snapshot = (
                (
                    await db.execute(
                        sa.select(D)
                        .where(D.c.user_id == target.user_id)
                        .with_for_update()
                    )
                )
                .mappings()
                .one()
            )
            if snapshot["attempt_id"] != target.attempt_id:
                return "superseded"
            outcome = result.outcome if current else "identity_changed"
            values: dict[str, Any] = dict(
                last_outcome=outcome, next_attempt_at=at + REFRESH
            )
            if outcome in {
                "credentials",
                "rate_limit",
                "network",
                "provider_error",
                "invalid_request",
            }:
                values["next_attempt_at"] = at + timedelta(days=1)
            if outcome == "success" and result.profile is not None:
                values.update(
                    _snapshot_values(snapshot, target, result, context, at)
                )
                outcome = values["last_outcome"]
            await db.execute(
                sa.update(D)
                .where(D.c.user_id == target.user_id)
                .values(**values)
            )
            return outcome

    async def release(self, lease: UUID, outcome: str) -> None:
        async with self.sessions.begin() as db:
            await db.execute(
                sa.update(C)
                .where(C.c.lease_id == lease)
                .values(
                    lease_id=None,
                    lease_until=None,
                    last_outcome=outcome,
                )
            )


def _snapshot_values(old, target, result, context, at) -> dict[str, Any]:
    profile = result.profile
    same = (
        old["observed_meta_id"] == target.meta_id
        and old["identity_context"] == target.identity_context
        and old["discovery_context"] == context
        and (old["username"] or "").lower() == target.username.lower()
    )
    if profile.username.lower() != target.username.lower() or (
        same and old["discovery_object_id"] != profile.object_id
    ):
        return dict(last_outcome="identity_conflict")
    details = dict(old["details"]) if same else {}
    details.update(
        {
            key: {"value": value, "observed_at": at.isoformat()}
            for key, value in profile.details.items()
        }
    )
    values = dict(
        last_outcome="success",
        observed_meta_id=target.meta_id,
        identity_context=target.identity_context,
        username=profile.username,
        discovery_object_id=profile.object_id,
        discovery_context=context,
        observed_at=at,
        details=details,
    )
    for field in ("followers", "media"):
        value = getattr(profile, f"{field}_count")
        if value is not None or not same:
            values[f"{field}_count"] = value
            values[f"{field}_observed_at"] = at if value is not None else None
    return values
