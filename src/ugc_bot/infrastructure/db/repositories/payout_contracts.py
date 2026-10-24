"""Caller-transaction persistence for readable payout companions."""

from sqlalchemy import insert, select, text

from ugc_bot.application.payout_contract_ports import PayoutFieldDefinition
from ugc_bot.application.payout_contracts import (
    document_hash,
    field_definitions,
)
from ugc_bot.infrastructure.db.payout_contract_models import TABLE_MAP
from ugc_bot.infrastructure.db.payout_models import TABLE_MAP as PAYOUT
from ugc_bot.infrastructure.db.repositories.financial_ledger import (
    _session,
)


class SqlAlchemyPayoutContractRepository:
    async def available(self, *, session):
        return bool(
            await _session(session).scalar(
                text(
                    "SELECT count(*)=3 FROM pg_catalog.pg_class c "
                    "JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace "
                    "WHERE n.nspname=current_schema() AND c.relkind='r' "
                    "AND c.relname IN ('financial_payout_terms_documents',"
                    "'financial_payout_requirement_contracts',"
                    "'financial_payout_requisites_acceptances')"
                )
            )
        )

    async def add(self, kind, values, *, session):
        await _session(session).execute(
            insert(TABLE_MAP[kind]).values(**values)
        )

    async def document(self, identity, *, session):
        table = TABLE_MAP["documents"]
        row = (
            (
                await _session(session).execute(
                    select(table).where(table.c.document_id == identity)
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None or document_hash(row["content_text"]) != row["sha256"]:
            raise ValueError("payout_readable_terms_required")
        return dict(row)

    async def contract(self, requirements, *, session):
        if not await self.available(session=session):
            return None
        table = TABLE_MAP["bindings"]
        row = (
            (
                await _session(session).execute(
                    select(table).where(
                        table.c.requirements_id
                        == requirements["requirements_id"]
                    )
                )
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            return None
        try:
            document = await self.document(row["document_id"], session=session)
            if document["sha256"] != row["sha256"]:
                return None
            definitions = field_definitions(
                tuple(
                    PayoutFieldDefinition(**v) for v in row["field_definitions"]
                ),
                requirements["required_fields"],
                document["source_locale"],
            )
            return dict(document=document, field_definitions=definitions)
        except (ValueError, TypeError, KeyError):
            return None

    async def acceptance(self, identity, *, session):
        if not await self.available(session=session):
            return None
        table = TABLE_MAP["acceptances"]
        return (
            (
                await _session(session).execute(
                    select(table).where(table.c.requisites_id == identity)
                )
            )
            .mappings()
            .one_or_none()
        )

    async def accepted_contract(self, requisites, *, session):
        requirements = PAYOUT["requirements"]
        row = (
            (
                await _session(session).execute(
                    select(requirements).where(
                        requirements.c.requirements_id
                        == requisites["requirements_id"]
                    )
                )
            )
            .mappings()
            .one()
        )
        contract = await self.contract(row, session=session)
        accepted = await self.acceptance(
            requisites["requisites_id"], session=session
        )
        if (
            contract is None
            or accepted is None
            or accepted["accepted"] is not True
            or (
                accepted["recipient_id"],
                accepted["requirements_id"],
                accepted["document_id"],
                accepted["sha256"],
            )
            != (
                requisites["recipient_id"],
                requisites["requirements_id"],
                contract["document"]["document_id"],
                contract["document"]["sha256"],
            )
        ):
            raise ValueError("payout_readable_acceptance_required")
        return contract

    async def own_requisites(self, actor_id, *, session):
        table, requirements = PAYOUT["requisites"], PAYOUT["requirements"]
        return (
            (
                await _session(session).execute(
                    select(
                        table,
                        requirements.c.version.label("requirements_version"),
                    )
                    .join(
                        requirements,
                        requirements.c.requirements_id
                        == table.c.requirements_id,
                    )
                    .where(table.c.recipient_id == actor_id)
                    .order_by(table.c.recorded_at, table.c.requisites_id)
                )
            )
            .mappings()
            .all()
        )
