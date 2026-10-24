"""Exact pre-companion commands and ciphertext survive the actual upgrade."""

import base64
import os
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import insert, inspect, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from tests.helpers.financial_environment import (
    isolated_financial_database,
    upgrade_financial_schema,
)
from tests.helpers.payout_contracts import acceptance_fields, publication_fields
from ugc_bot.application.collaboration_ports import canonical
from ugc_bot.application.payout_ports import (
    PublishPayoutRequirements,
    StorePayoutRequisites,
    payout_payload_hash,
)
from ugc_bot.container.payout_factory import build_payout_service
from ugc_bot.domain.enums import MessengerType, UserStatus
from ugc_bot.infrastructure.db.models import UserModel
from ugc_bot.infrastructure.db.payout_models import TABLE_MAP
from ugc_bot.infrastructure.db.session import SessionTransactionManager


@pytest.mark.asyncio
async def test_actual_prior_p01_hash_and_ciphertext_survive_companion(config):
    now = datetime.now(timezone.utc)
    owner, admin, requirements_id, requisites_id = (uuid4() for _ in range(4))
    config.financial.core_enabled = config.financial.payouts_enabled = True
    config.financial.requisites_key = SecretStr(
        base64.urlsafe_b64encode(os.urandom(32)).decode()
    )
    config.financial.requisites_key_id = "synthetic-old-key"
    with isolated_financial_database(
        os.environ["FINANCIAL_TEST_DATABASE_URL"],
        target_revision="financial_payout_v1",
    ) as engine:
        assert (
            "financial_payout_terms_documents"
            not in inspect(engine).get_table_names()
        )
        async_engine = create_async_engine(engine.url)
        factory = async_sessionmaker(async_engine, expire_on_commit=False)
        tm = SessionTransactionManager(factory)
        service = build_payout_service(config, tm, factory)
        service.clock = type("Clock", (), {"now": lambda self: now})()
        details = dict(
            recipient_name="Synthetic prior recipient",
            bank_account="old-private-account-1234",
            legal_status="synthetic",
        )
        publication_payload = dict(
            actor_id=admin,
            operation_key="prior-publication",
            reason="Synthetic prior opaque P01 record",
            expected_version=0,
            effective_from=now,
            legal_reference="synthetic:prior-legal",
            terms_reference="synthetic:prior-terms",
            evidence_reference="synthetic:prior-proof",
            required_fields=("recipient_name", "bank_account", "legal_status"),
            enabled=True,
        )
        store_payload = dict(
            actor_id=owner,
            operation_key="prior-secret",
            requirements_id=requirements_id,
            accepted_terms_reference="synthetic:prior-terms",
            details=details,
        )
        # These literal prior-shape payloads intentionally do not use the new
        # command encoder. There are no companion defaults in old hashes.
        stored_hash = payout_payload_hash(
            store_payload
            | {"details": service.crypto.fingerprint(details, owner)}
        )
        published_hash = payout_payload_hash(publication_payload)
        publication_result = canonical(
            dict(
                requirements_id=requirements_id,
                version=1,
                actor_id=admin,
                recorded_at=now,
                effective_from=now,
                legal_reference=publication_payload["legal_reference"],
                terms_reference=publication_payload["terms_reference"],
                evidence_reference=publication_payload["evidence_reference"],
                reason=publication_payload["reason"],
                required_fields=publication_payload["required_fields"],
                enabled=True,
            )
        )
        store_result = canonical(
            dict(
                requisites_id=requisites_id,
                requirements_id=requirements_id,
                masked_label="••••1234",
            )
        )
        sealed = service.crypto.seal(details, owner, requisites_id)
        with Session(engine) as db, db.begin():
            db.add_all(
                [
                    UserModel(
                        user_id=u,
                        username="synthetic-prior",
                        messenger_type=MessengerType.TELEGRAM,
                        status=UserStatus.ACTIVE,
                        admin=u == admin,
                    )
                    for u in (owner, admin)
                ]
            )
            db.flush()
            db.execute(
                insert(TABLE_MAP["requirements"]).values(
                    **(
                        publication_result
                        | {
                            "requirements_id": requirements_id,
                            "actor_id": admin,
                            "recorded_at": now,
                            "effective_from": now,
                        }
                    )
                )
            )
            db.execute(
                insert(TABLE_MAP["requisites"]).values(
                    requisites_id=requisites_id,
                    recipient_id=owner,
                    requirements_id=requirements_id,
                    recorded_at=now,
                    **sealed,
                )
            )
            for actor, key, action, digest, result in (
                (
                    admin,
                    "prior-publication",
                    "PublishPayoutRequirements",
                    published_hash,
                    publication_result,
                ),
                (
                    owner,
                    "prior-secret",
                    "StorePayoutRequisites",
                    stored_hash,
                    store_result,
                ),
            ):
                db.execute(
                    insert(TABLE_MAP["commands"]).values(
                        command_id=uuid4(),
                        actor_id=actor,
                        operation_key=key,
                        action=action,
                        payload_hash=digest,
                        recorded_at=now,
                        result=result,
                    )
                )

        async def execute(command):
            async with tm.transaction() as db:
                return await service.execute(command, session=db)

        try:
            assert (
                await execute(PublishPayoutRequirements(**publication_payload))
                == publication_result
            )
            assert (
                await execute(StorePayoutRequisites(**store_payload))
                == store_result
            )
            # New opaque acceptance is unavailable even before deployment of
            # the companion, while an exact retained replay stays valid.
            with pytest.raises(
                ValueError, match="payout_readable_terms_required"
            ):
                await execute(
                    StorePayoutRequisites(
                        **(
                            store_payload
                            | {"operation_key": "new-opaque-before"}
                        )
                    )
                )
            with pytest.raises(
                ValueError, match="payout_readable_terms_required"
            ):
                await execute(
                    PublishPayoutRequirements(
                        **(
                            publication_payload
                            | dict(
                                operation_key="missing-companion-publication",
                                expected_version=1,
                                **publication_fields(),
                            )
                        )
                    )
                )
            upgrade_financial_schema(
                engine, target_revision="financial_payout_contracts_v1"
            )
            assert (
                await execute(PublishPayoutRequirements(**publication_payload))
                == publication_result
            )
            assert (
                await execute(StorePayoutRequisites(**store_payload))
                == store_result
            )
            async with tm.transaction() as db:
                current = await service.requirements_for_actor(
                    owner, session=db
                )
                old_masked = await service.requisites_for_actor(
                    owner, session=db
                )
            assert not current["readable"] and current["document"] is None
            assert (
                old_masked[0]["usable"] is False
                and old_masked[0]["document_id"] is None
            )
            with pytest.raises(
                ValueError, match="payout_readable_terms_required"
            ):
                await execute(
                    StorePayoutRequisites(
                        **(
                            store_payload
                            | {"operation_key": "new-opaque-after"}
                        )
                    )
                )
            published = await execute(
                PublishPayoutRequirements(
                    **(
                        publication_payload
                        | dict(
                            operation_key="actual-companion-publication",
                            expected_version=1,
                            **publication_fields(),
                        )
                    )
                )
            )
            await execute(
                StorePayoutRequisites(
                    **(
                        store_payload
                        | dict(
                            operation_key="actual-readable-acceptance",
                            requirements_id=published["requirements_id"],
                            **acceptance_fields(published),
                        )
                    )
                )
            )
            service.crypto = None
            async with tm.transaction() as db:
                recovered = await service.operation_for_actor(
                    owner, "prior-secret", session=db
                )
                masked = await service.requisites_for_actor(owner, session=db)
            assert recovered["result"] == store_result and recovered["recorded"]
            assert len(masked) == 2 and all(not row["usable"] for row in masked)
            assert details["bank_account"] not in str(masked) + str(recovered)
            with Session(engine) as db:
                old = (
                    db.execute(
                        select(TABLE_MAP["requisites"]).where(
                            TABLE_MAP["requisites"].c.requisites_id
                            == requisites_id
                        )
                    )
                    .mappings()
                    .one()
                )
                assert bytes(old["ciphertext"]) == sealed["ciphertext"]
                commands = (
                    db.execute(
                        select(TABLE_MAP["commands"]).where(
                            TABLE_MAP["commands"].c.operation_key.in_(
                                ("prior-publication", "prior-secret")
                            )
                        )
                    )
                    .mappings()
                    .all()
                )
                assert {r["payload_hash"] for r in commands} == {
                    stored_hash,
                    published_hash,
                }
                assert {r["operation_key"]: r["result"] for r in commands} == {
                    "prior-publication": publication_result,
                    "prior-secret": store_result,
                }
        finally:
            await async_engine.dispose()


def test_empty_companion_round_trip_is_bounded_to_its_own_tables():
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    from ugc_bot.infrastructure.db.migrations.versions import (
        financial_payout_contracts_v1 as migration,
    )

    with (
        isolated_financial_database(
            os.environ["FINANCIAL_TEST_DATABASE_URL"],
            target_revision="financial_payout_contracts_v1",
        ) as engine,
        engine.begin() as db,
        Operations.context(MigrationContext.configure(db)),
    ):
        migration.downgrade()
        assert (
            "financial_payout_terms_documents"
            not in inspect(db).get_table_names()
        )
        assert "financial_payout_requests" in inspect(db).get_table_names()
        migration.upgrade()
        assert (
            "financial_payout_terms_documents" in inspect(db).get_table_names()
        )
