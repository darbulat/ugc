"""The additive companion follows the assigned parent and protects its facts."""

import os

import pytest
from sqlalchemy import inspect

from tests.helpers.financial_environment import (
    isolated_financial_database,
    upgrade_financial_schema,
)


def test_assigned_parent_upgrade_preserves_existing_metadata():
    from ugc_bot.infrastructure.db.correction_models import TABLE_MAP
    from ugc_bot.infrastructure.db.migrations.versions import (
        financial_corrections_a1 as migration,
    )

    assert migration.down_revision == "campaign_drafts_v1"
    with isolated_financial_database(
        os.environ["FINANCIAL_TEST_DATABASE_URL"],
        target_revision="campaign_drafts_v1",
    ) as engine:
        before = set(inspect(engine).get_table_names())
        upgrade_financial_schema(engine, target_revision=migration.revision)
        assert set(inspect(engine).get_table_names()) == before | {
            t.name for t in TABLE_MAP.values()
        }


def test_owned_metadata_creation_installs_guards_and_replays_safely():
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    from ugc_bot.infrastructure.db.base import Base
    from ugc_bot.infrastructure.db.correction_models import TABLES

    with isolated_financial_database(
        os.environ["FINANCIAL_TEST_DATABASE_URL"],
        target_revision="campaign_drafts_v1",
    ) as engine:
        Base.metadata.create_all(engine, tables=TABLES)
        Base.metadata.create_all(engine, tables=TABLES)
        with engine.begin() as db:
            for table in TABLES:
                if table.name == "financial_correction_states":
                    continue
                with (
                    pytest.raises(
                        DBAPIError, match="correction_fact_immutable"
                    ),
                    db.begin_nested(),
                ):
                    db.execute(text(f"DELETE FROM {table.name}"))


def test_empty_companion_round_trip_and_metadata_constraints(
    financial_pg_engine,
):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import UniqueConstraint

    from ugc_bot.infrastructure.db.correction_models import TABLE_MAP
    from ugc_bot.infrastructure.db.migrations.versions import (
        financial_corrections_a1 as migration,
    )

    with (
        isolated_financial_database(
            os.environ["FINANCIAL_TEST_DATABASE_URL"],
            target_revision="financial_corrections_a1",
        ) as engine,
        engine.begin() as db,
        Operations.context(MigrationContext.configure(db)),
    ):
        migration.downgrade()
        assert not set(t.name for t in TABLE_MAP.values()) & set(
            inspect(db).get_table_names()
        )
        migration.upgrade()
        for table in TABLE_MAP.values():
            actual = inspect(db)
            assert {
                tuple(x["column_names"])
                for x in actual.get_unique_constraints(table.name)
            } == {
                tuple(c.columns.keys())
                for c in table.constraints
                if isinstance(c, UniqueConstraint)
            }
            assert {
                x["name"] for x in actual.get_check_constraints(table.name)
            } == {
                c.name
                for c in table.constraints
                if c.__class__.__name__ == "CheckConstraint"
            }
            assert [
                (c["name"], c["nullable"])
                for c in actual.get_columns(table.name)
            ] == [(c.name, c.nullable) for c in table.c]


def test_populated_companion_downgrade_refuses_without_discarding_facts(
    financial_pg_engine,
):
    from datetime import datetime, timezone
    from uuid import uuid4

    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import insert, select

    from ugc_bot.domain.enums import MessengerType, UserStatus
    from ugc_bot.infrastructure.db.correction_models import TABLE_MAP
    from ugc_bot.infrastructure.db.migrations.versions import (
        financial_corrections_a1 as migration,
    )
    from ugc_bot.infrastructure.db.models import UserModel

    actor, command = uuid4(), uuid4()
    from sqlalchemy.orm import Session

    with Session(financial_pg_engine) as db, db.begin():
        db.add(
            UserModel(
                user_id=actor,
                username="synthetic-downgrade",
                messenger_type=MessengerType.TELEGRAM,
                status=UserStatus.ACTIVE,
            )
        )
        db.flush()
        db.execute(
            insert(TABLE_MAP["commands"]).values(
                command_id=command,
                actor_id=actor,
                operation_key="retained",
                action="RequestSelectionRefund",
                payload_hash="a" * 64,
                recorded_at=datetime.now(timezone.utc),
                result={"original": True},
            )
        )
    with (
        financial_pg_engine.begin() as db,
        Operations.context(MigrationContext.configure(db)),
    ):
        with pytest.raises(
            RuntimeError, match="Cannot discard immutable correction history"
        ):
            migration.downgrade()
        assert db.execute(
            select(TABLE_MAP["commands"].c.result).where(
                TABLE_MAP["commands"].c.command_id == command
            )
        ).scalar_one() == {"original": True}


@pytest.mark.asyncio
async def test_parent_payout_hashes_receipts_and_ciphertext_are_preserved(
    config,
):
    import base64
    from datetime import datetime, timezone
    from uuid import UUID, uuid4

    from pydantic import SecretStr
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.orm import Session

    from tests.helpers.payout_contracts import (
        acceptance_fields,
        publication_fields,
    )
    from ugc_bot.application.payout_ports import (
        PublishPayoutRequirements,
        StorePayoutRequisites,
    )
    from ugc_bot.container.payout_factory import build_payout_service
    from ugc_bot.domain.enums import MessengerType, UserStatus
    from ugc_bot.infrastructure.db.models import UserModel
    from ugc_bot.infrastructure.db.payout_models import TABLE_MAP
    from ugc_bot.infrastructure.db.session import SessionTransactionManager

    now = datetime.now(timezone.utc)
    admin, owner = uuid4(), uuid4()
    config.financial.core_enabled = config.financial.payouts_enabled = True
    config.financial.requisites_key = SecretStr(
        base64.urlsafe_b64encode(os.urandom(32)).decode()
    )
    config.financial.requisites_key_id = "synthetic-correction-upgrade"
    with isolated_financial_database(
        os.environ["FINANCIAL_TEST_DATABASE_URL"],
        target_revision="campaign_drafts_v1",
    ) as engine:
        with Session(engine) as db, db.begin():
            db.add_all(
                [
                    UserModel(
                        user_id=i,
                        username="synthetic-prior",
                        messenger_type=MessengerType.TELEGRAM,
                        status=UserStatus.ACTIVE,
                        admin=i == admin,
                    )
                    for i in (admin, owner)
                ]
            )
        async_engine = create_async_engine(engine.url)
        factory = async_sessionmaker(async_engine, expire_on_commit=False)
        tm = SessionTransactionManager(factory)
        service = build_payout_service(config, tm, factory)
        service.clock = type("Clock", (), {"now": lambda self: now})()
        publication = PublishPayoutRequirements(
            actor_id=admin,
            operation_key="synthetic-before-companion",
            reason="Synthetic parent preservation fixture",
            expected_version=0,
            effective_from=now,
            legal_reference="synthetic:legal",
            terms_reference="synthetic:terms",
            evidence_reference="synthetic:evidence",
            required_fields=("recipient_name", "bank_account", "legal_status"),
            **publication_fields(),
        )
        try:
            async with tm.transaction() as db:
                published = await service.execute(publication, session=db)
            store = StorePayoutRequisites(
                actor_id=owner,
                operation_key="synthetic-secret-before-companion",
                requirements_id=UUID(str(published["requirements_id"])),
                accepted_terms_reference="synthetic:terms",
                details={
                    "recipient_name": "Synthetic owner",
                    "bank_account": "synthetic-private-1234",
                    "legal_status": "synthetic",
                },
                **acceptance_fields(published),
            )
            async with tm.transaction() as db:
                receipt = await service.execute(store, session=db)

            def persisted():
                with Session(engine) as db:
                    commands = [
                        dict(r)
                        for r in db.execute(
                            select(TABLE_MAP["commands"])
                        ).mappings()
                    ]
                    ciphertext = bytes(
                        db.execute(
                            select(TABLE_MAP["requisites"].c.ciphertext)
                        ).scalar_one()
                    )
                    return commands, ciphertext

            before = persisted()
            upgrade_financial_schema(
                engine, target_revision="financial_corrections_a1"
            )
            assert persisted() == before
            async with tm.transaction() as db:
                assert (
                    await service.execute(publication, session=db) == published
                )
                assert await service.execute(store, session=db) == receipt
        finally:
            await async_engine.dispose()
