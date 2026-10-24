"""Readable publication is real immutable server data, not an opaque string."""

import pytest
from sqlalchemy import inspect

from tests.postgres_financial.test_payout_runtime import (
    capture_env as capture_env,
)
from tests.postgres_financial.test_payout_runtime import (
    payout_env as payout_env,
)

__all__ = ["capture_env", "payout_env"]


def test_readable_publication_companion_is_migrated(financial_pg_engine):
    assert {
        "financial_payout_terms_documents",
        "financial_payout_requirement_contracts",
        "financial_payout_requisites_acceptances",
    } <= set(inspect(financial_pg_engine).get_table_names())


@pytest.mark.asyncio
async def test_enabled_publication_requires_readable_document(payout_env):
    from dataclasses import replace

    env = payout_env
    with pytest.raises(ValueError, match="payout_readable_terms_required"):
        await env["execute"](
            replace(
                env["publication"],
                operation_key="new-opaque",
                document=None,
                field_definitions=None,
                expected_version=env["requirements"]["version"],
            )
        )


@pytest.mark.asyncio
async def test_exact_document_fields_and_acceptance_are_atomic(payout_env):
    import hashlib
    from dataclasses import replace

    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from tests.helpers.payout_contracts import (
        acceptance_fields,
        publication_fields,
    )
    from ugc_bot.application.payout_contract_ports import TermsDocumentInput
    from ugc_bot.infrastructure.db.payout_contract_models import TABLE_MAP

    env = payout_env
    text = "  Synthetic test source <b>data only</b>\nSecond line.  "
    fields = publication_fields()["field_definitions"]
    fields = tuple(
        replace(v, allowed_values=("synthetic-fixture",))
        if v.key == "legal_status"
        else v
        for v in fields
    )
    publication = await env["execute"](
        replace(
            env["publication"],
            operation_key="exact-document",
            expected_version=env["requirements"]["version"],
            document=TermsDocumentInput(content_text=text, source_locale="en"),
            field_definitions=fields,
        )
    )
    assert publication["document"]["content_text"] == text
    assert (
        publication["document"]["sha256"]
        == hashlib.sha256(text.encode()).hexdigest()
    )
    stored = await env["execute"](
        replace(
            env["store"],
            operation_key="exact-acceptance",
            requirements_id=publication["requirements_id"],
            **acceptance_fields(publication),
        )
    )
    with Session(env["pg"]) as db:
        acceptance = (
            db.execute(
                select(TABLE_MAP["acceptances"]).where(
                    TABLE_MAP["acceptances"].c.requisites_id
                    == stored["requisites_id"]
                )
            )
            .mappings()
            .one()
        )
        assert acceptance["accepted"] is True
        assert (
            str(acceptance["document_id"])
            == publication["document"]["document_id"]
        )
    async with env["flow"]["container"].transaction_manager.transaction() as db:
        public = await env["service"].requirements_for_actor(
            env["flow"]["manager"], session=db
        )
    assert public["readable"] and public["document"]["content_text"] == text
    assert (
        "evidence_reference" not in public and "legal_reference" not in public
    )
    with pytest.raises(
        ValueError, match="payout_requisites_permitted_value_required"
    ):
        await env["execute"](
            replace(
                env["store"],
                operation_key="invalid-permitted",
                requirements_id=publication["requirements_id"],
                details=env["details"] | {"legal_status": "not-published"},
                **acceptance_fields(publication),
            )
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change,code",
    [
        ({"accepted": None}, "payout_acceptance_required"),
        ({"accepted": False}, "payout_acceptance_required"),
        ({"accepted_document_hash": "0" * 64}, "payout_document_mismatch"),
        ({"accepted_document_id": None}, "payout_document_mismatch"),
    ],
)
async def test_unseen_or_implicit_acceptance_never_stores_secret(
    payout_env, change, code
):
    from dataclasses import replace

    from tests.postgres_financial.test_payout_runtime import rows

    env = payout_env
    before = len(rows(env, "requisites"))
    with pytest.raises(ValueError, match=code):
        await env["execute"](
            replace(env["store"], operation_key="bad-acceptance", **change)
        )
    assert len(rows(env, "requisites")) == before


@pytest.mark.asyncio
async def test_disabled_publication_needs_no_invented_document(payout_env):
    from dataclasses import replace
    from uuid import UUID

    from ugc_bot.application.payout_contract_ports import TermsDocumentInput

    env = payout_env
    publication = await env["execute"](
        replace(
            env["publication"],
            operation_key="suspend-no-text",
            expected_version=env["requirements"]["version"],
            enabled=False,
            document=None,
            field_definitions=None,
        )
    )
    assert publication["document"] is None and not publication["readable"]
    retained = await env["execute"](
        replace(
            env["publication"],
            operation_key="suspend-existing-doc",
            expected_version=publication["version"],
            enabled=False,
            document=TermsDocumentInput(
                document_id=UUID(env["requirements"]["document"]["document_id"])
            ),
        )
    )
    assert retained["document"] == env["requirements"]["document"]
    assert retained["readable"] and not retained["enabled"]


@pytest.mark.asyncio
async def test_document_publication_rollback_leaves_no_orphan(
    payout_env, monkeypatch
):
    from dataclasses import replace

    from sqlalchemy import func, select
    from sqlalchemy.orm import Session

    from ugc_bot.infrastructure.db.payout_contract_models import TABLE_MAP

    env = payout_env
    with Session(env["pg"]) as db:
        before = {
            k: db.scalar(select(func.count()).select_from(t))
            for k, t in TABLE_MAP.items()
        }
    original = env["service"].repository.contracts.add

    async def fail(kind, values, *, session):
        if kind == "bindings":
            raise ValueError("synthetic-publication-rollback")
        await original(kind, values, session=session)

    monkeypatch.setattr(env["service"].repository.contracts, "add", fail)
    with pytest.raises(ValueError, match="synthetic-publication-rollback"):
        await env["execute"](
            replace(
                env["publication"],
                operation_key="rollback-doc",
                expected_version=env["requirements"]["version"],
            )
        )
    with Session(env["pg"]) as db:
        assert {
            k: db.scalar(select(func.count()).select_from(t))
            for k, t in TABLE_MAP.items()
        } == before


@pytest.mark.asyncio
async def test_admin_history_retains_exact_future_readable_publication(
    payout_env,
):
    from dataclasses import replace
    from datetime import timedelta

    env = payout_env
    future = await env["execute"](
        replace(
            env["publication"],
            operation_key="future-readable",
            expected_version=env["requirements"]["version"],
            effective_from=env["flow"]["clock"].at + timedelta(days=1),
        )
    )
    async with env["flow"]["container"].transaction_manager.transaction() as db:
        history = await env["service"].requirements_for_admin(
            env["client"], session=db
        )
        current = await env["service"].requirements_for_actor(
            env["flow"]["manager"], session=db
        )
    latest = next(
        v for v in history if v["requirements_id"] == future["requirements_id"]
    )
    assert latest["readable"] is True
    assert latest["document"] == future["document"]
    assert latest["field_definitions"] == future["field_definitions"]
    assert current["requirements_id"] == env["requirements"]["requirements_id"]


@pytest.mark.asyncio
async def test_acceptance_rollback_has_no_secret_or_command(
    payout_env, monkeypatch
):
    from dataclasses import replace

    from tests.postgres_financial.test_payout_runtime import rows

    env = payout_env
    before = rows(env, "requisites"), rows(env, "commands")
    original = env["service"].repository.contracts.add

    async def fail(kind, values, *, session):
        if kind == "acceptances":
            raise ValueError("synthetic-acceptance-rollback")
        return await original(kind, values, session=session)

    monkeypatch.setattr(env["service"].repository.contracts, "add", fail)
    with pytest.raises(ValueError, match="synthetic-acceptance-rollback"):
        await env["execute"](
            replace(env["store"], operation_key="rollback-acceptance")
        )
    assert (rows(env, "requisites"), rows(env, "commands")) == before


@pytest.mark.parametrize("kind", ["documents", "bindings", "acceptances"])
@pytest.mark.parametrize("verb", ["UPDATE", "DELETE", "TRUNCATE"])
@pytest.mark.asyncio
async def test_contract_facts_cannot_be_rewritten_or_truncated(
    payout_env, kind, verb
):
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError
    from sqlalchemy.orm import Session

    from ugc_bot.infrastructure.db.payout_contract_models import TABLE_MAP

    table = TABLE_MAP[kind]
    suffix = (
        " SET " + list(table.c)[0].name + "=" + list(table.c)[0].name
        if verb == "UPDATE"
        else " CASCADE"
        if verb == "TRUNCATE"
        else ""
    )
    with Session(payout_env["pg"]) as db:
        with pytest.raises(DBAPIError, match="payout_contract_immutable"):
            db.execute(
                text(
                    f"{verb} "
                    + ("FROM " if verb == "DELETE" else "")
                    + table.name
                    + suffix
                )
            )
        db.rollback()


@pytest.mark.asyncio
async def test_populated_contract_downgrade_preserves_all_facts(payout_env):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy.orm import Session

    from ugc_bot.infrastructure.db.migrations.versions import (
        financial_payout_contracts_v1 as migration,
    )

    with (
        Session(payout_env["pg"]) as db,
        db.begin(),
        Operations.context(MigrationContext.configure(db.connection())),
        pytest.raises(
            RuntimeError, match="Cannot discard immutable payout contracts"
        ),
    ):
        migration.downgrade()
    assert (
        "financial_payout_terms_documents"
        in inspect(payout_env["pg"]).get_table_names()
    )


@pytest.mark.asyncio
async def test_changed_publication_rejects_old_acceptance_and_reserve(
    payout_env,
):
    from dataclasses import replace

    from tests.postgres_financial.test_payout_runtime import (
        request_command,
        rows,
    )

    env = payout_env
    publication = await env["execute"](
        replace(
            env["publication"],
            operation_key="changed-readable",
            expected_version=env["requirements"]["version"],
        )
    )
    with pytest.raises(ValueError, match="payout_requirements_changed"):
        await env["execute"](
            replace(env["store"], operation_key="stale-publication-store")
        )
    with pytest.raises(ValueError, match="payout_requirements_changed"):
        await env["execute"](
            request_command(env, operation_key="stale-requisites-reserve")
        )
    with pytest.raises(ValueError, match="payout_document_mismatch"):
        await env["execute"](
            replace(
                env["store"],
                operation_key="old-proof-new-publication",
                requirements_id=publication["requirements_id"],
            )
        )
    assert not [
        row
        for row in rows(env, "requests")
        if row["recipient_id"] == env["flow"]["manager"]
    ]


@pytest.mark.asyncio
async def test_unknown_existing_document_has_no_new_publication(payout_env):
    from dataclasses import replace
    from uuid import uuid4

    from tests.postgres_financial.test_payout_runtime import rows
    from ugc_bot.application.payout_contract_ports import TermsDocumentInput

    env = payout_env
    before = rows(env, "requirements")
    with pytest.raises(ValueError, match="payout_readable_terms_required"):
        await env["execute"](
            replace(
                env["publication"],
                operation_key="missing-actual-document",
                expected_version=env["requirements"]["version"],
                document=TermsDocumentInput(document_id=uuid4()),
            )
        )
    assert rows(env, "requirements") == before


@pytest.mark.asyncio
@pytest.mark.parametrize("definitions", [[{"invalid": "shape"}], ["invalid"]])
async def test_malformed_immutable_field_metadata_is_unavailable(
    payout_env, definitions
):
    from dataclasses import replace
    from uuid import UUID

    from sqlalchemy import insert
    from sqlalchemy.orm import Session

    from ugc_bot.infrastructure.db.payout_contract_models import TABLE_MAP

    env = payout_env
    disabled = await env["execute"](
        replace(
            env["publication"],
            operation_key="synthetic-disabled-corrupt-metadata",
            expected_version=env["requirements"]["version"],
            enabled=False,
            document=None,
            field_definitions=None,
        )
    )
    document = env["requirements"]["document"]
    # A deliberately malformed synthetic immutable fact tests read failure,
    # never a bypass that turns opaque history into an authorized acceptance.
    with Session(env["pg"]) as db, db.begin():
        db.execute(
            insert(TABLE_MAP["bindings"]).values(
                requirements_id=UUID(disabled["requirements_id"]),
                document_id=UUID(document["document_id"]),
                sha256=document["sha256"],
                field_definitions=definitions,
            )
        )
    async with env["flow"]["container"].transaction_manager.transaction() as db:
        view = await env["service"].requirements_for_actor(
            env["flow"]["manager"], session=db
        )
    assert (
        not view["readable"]
        and view["document"] is None
        and view["field_definitions"] is None
    )
