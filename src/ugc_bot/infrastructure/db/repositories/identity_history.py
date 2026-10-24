"""Read historical facts in the payment caller's transaction."""

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import RowMapping, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ugc_bot.domain.identity_history import (
    DirectBindingObservation,
    HistoricalBindingInputs,
    IdentityCountInputs,
    IdentityHistoryCoverage,
    IdentityHistoryUnavailable,
    IdentityObservation,
)
from ugc_bot.infrastructure.db.identity_history_models import (
    IDENTITY_OBSERVATIONS,
)
from ugc_bot.infrastructure.db.identity_history_schema import (
    BINDING_HASH,
    HISTORY_SNAPSHOT_LOCK_SQL,
    PROFILE_HASH,
)
from ugc_bot.infrastructure.db.repositories._shared import _resolve_session


def _binding(row: RowMapping) -> DirectBindingObservation:
    return DirectBindingObservation(
        row["observation_sequence"],
        row["referrer_user_id"],
        row["referred_user_id"],
        row["active"],
        row["created_at"],
        row["observed_at"],
        row["source"],
        row["business_key"],
        row["registered_at"],
    )


async def _read_coverage(
    db: AsyncSession,
) -> tuple[IdentityHistoryCoverage | None, datetime]:
    if db.get_bind().dialect.name != "postgresql":
        return None, datetime.now(timezone.utc)
    installed = (
        (
            await db.execute(
                text("""
        SELECT clock_timestamp() AS checked_at,
            to_regclass('creator_identity_coverage') IS NOT NULL
            AND to_regclass('creator_identity_observations') IS NOT NULL
            AND to_regclass('creator_direct_binding_observations') IS NOT NULL
            AND to_regclass('blogger_profiles') IS NOT NULL
            AND to_regclass('user_referral_bindings') IS NOT NULL AS installed
    """)
            )
        )
        .mappings()
        .one()
    )
    if not installed["installed"]:
        return None, installed["checked_at"]
    coverage_row = (
        (
            await db.execute(
                text(f"""
        SELECT c.*, clock_timestamp() AS checked_at,
            (SELECT count(*) = 12 FROM pg_trigger
             WHERE NOT tgisinternal AND tgenabled IN ('O','A')
               AND tgname IN ('creator_profile_observation',
                   'creator_binding_observation',
                   'creator_identity_immutable',
                   'creator_binding_immutable',
                   'creator_coverage_immutable',
                   'creator_identity_no_truncate',
                   'creator_binding_no_truncate',
                   'creator_coverage_no_truncate',
                   'creator_profile_no_truncate',
                   'creator_canonical_binding_no_truncate',
                   'creator_profile_write_barrier',
                   'creator_binding_write_barrier')
               AND tgrelid IN (
                   'blogger_profiles'::regclass,
                   'user_referral_bindings'::regclass,
                   'creator_identity_observations'::regclass,
                   'creator_direct_binding_observations'::regclass,
                   'creator_identity_coverage'::regclass)
            ) AS capture_healthy,
            (SELECT count(*) FROM creator_identity_observations
             WHERE source='canonical_profile_cutover') AS actual_profiles,
            (SELECT {PROFILE_HASH} FROM creator_identity_observations
             WHERE source='canonical_profile_cutover') AS actual_profile_hash,
            (SELECT count(*) FROM creator_direct_binding_observations
             WHERE source='direct_binding_cutover') AS actual_bindings,
            (SELECT {BINDING_HASH} FROM creator_direct_binding_observations
             WHERE source='direct_binding_cutover') AS actual_binding_hash
        FROM creator_identity_coverage c WHERE coverage_key='v1'
    """)
            )
        )
        .mappings()
        .one_or_none()
    )
    checked_at = await db.scalar(text("SELECT clock_timestamp()"))
    if coverage_row is None:
        return None, checked_at
    complete = (
        coverage_row["capture_healthy"]
        and coverage_row["profile_seed_count"]
        == coverage_row["actual_profiles"]
        and coverage_row["binding_seed_count"]
        == coverage_row["actual_bindings"]
        and coverage_row["profile_seed_hash"]
        == coverage_row["actual_profile_hash"]
        and coverage_row["binding_seed_hash"]
        == coverage_row["actual_binding_hash"]
    )
    return IdentityHistoryCoverage(
        coverage_row["covered_from"], complete
    ), checked_at


@dataclass(slots=True)
class SqlAlchemyCreatorIdentityHistoryRepository:
    session_factory: async_sessionmaker[AsyncSession]

    async def acquire_snapshot_barrier(self, *, session: object | None) -> None:
        if (
            not isinstance(session, AsyncSession)
            or not session.in_transaction()
        ):
            raise ValueError("identity_snapshot_transaction_required")
        if session.get_bind().dialect.name != "postgresql":
            raise IdentityHistoryUnavailable(
                "identity_snapshot_postgres_transaction_required"
            )
        if await session.scalar(text("SHOW transaction_isolation")) != (
            "read committed"
        ):
            raise IdentityHistoryUnavailable(
                "identity_snapshot_read_committed_required"
            )
        await session.execute(text(HISTORY_SNAPSHOT_LOCK_SQL))

    async def read_direct_binding(
        self,
        referred_user_id: UUID,
        as_of: datetime,
        *,
        session: object | None = None,
    ) -> HistoricalBindingInputs:
        async with _resolve_session(self.session_factory, session) as db:
            coverage, checked_at = await _read_coverage(db)
            if coverage is None or not coverage.complete:
                return HistoricalBindingInputs(coverage, checked_at, None)
            row = (
                (
                    await db.execute(
                        text("""
                SELECT * FROM creator_direct_binding_observations
                WHERE referred_user_id=:referred AND observed_at<=:as_of
                ORDER BY observed_at DESC, observation_sequence DESC LIMIT 1
            """),
                        {"referred": referred_user_id, "as_of": as_of},
                    )
                )
                .mappings()
                .one_or_none()
            )
            return HistoricalBindingInputs(
                coverage, checked_at, _binding(row) if row is not None else None
            )

    async def read_network(
        self,
        partner_user_id: UUID,
        as_of: datetime,
        *,
        session: object | None = None,
    ) -> IdentityCountInputs:
        async with _resolve_session(self.session_factory, session) as db:
            coverage, checked_at = await _read_coverage(db)
            if coverage is None or not coverage.complete:
                return IdentityCountInputs(coverage, checked_at, (), ())
            binding_rows = (
                (
                    await db.execute(
                        text("""
                SELECT * FROM (
                    SELECT DISTINCT ON (referred_user_id) *
                    FROM creator_direct_binding_observations
                    WHERE observed_at <= :as_of
                    ORDER BY referred_user_id, observed_at DESC,
                             observation_sequence DESC
                ) latest WHERE referrer_user_id=:partner
            """),
                        {"as_of": as_of, "partner": partner_user_id},
                    )
                )
                .mappings()
                .all()
            )
            own_creators = [row["referred_user_id"] for row in binding_rows]
            identity_rows = (
                await db.execute(
                    select(IDENTITY_OBSERVATIONS).where(
                        IDENTITY_OBSERVATIONS.c.observed_at <= as_of,
                        IDENTITY_OBSERVATIONS.c.creator_user_id.in_(
                            own_creators
                        ),
                    )
                )
            ).mappings()
            identities = tuple(
                IdentityObservation(
                    row["observation_sequence"],
                    row["creator_user_id"],
                    row["instagram_user_id"],
                    row["active"],
                    row["observed_at"],
                    row["fact_at"],
                    row["source"],
                    row["business_key"],
                )
                for row in identity_rows
            )
            return IdentityCountInputs(
                coverage,
                checked_at,
                identities,
                tuple(_binding(row) for row in binding_rows),
            )
