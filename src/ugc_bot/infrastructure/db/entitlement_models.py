"""Immutable, atomic consumer receipts; no mutable balance authority."""

from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from ugc_bot.infrastructure.db.base import Base


class ClientEntitlementReceiptModel(Base):
    __tablename__ = "financial_client_assessments"
    event_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        sa.ForeignKey("outbox_events.event_id"),
        primary_key=True,
    )
    order_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), sa.ForeignKey("orders.order_id"), nullable=False
    )
    payment_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        sa.ForeignKey("payments.payment_id"),
        nullable=False,
        unique=True,
    )
    source_hash: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    assessment: Mapped[dict] = mapped_column(
        sa.JSON().with_variant(JSONB(), "postgresql"), nullable=False
    )
    recorded_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )


TABLES: tuple[sa.Table, ...] = (
    Base.metadata.tables[ClientEntitlementReceiptModel.__tablename__],
)
sa.event.listen(
    TABLES[0],
    "after_create",
    sa.DDL("""
CREATE OR REPLACE FUNCTION financial_entitlement_deny_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$ BEGIN
 RAISE EXCEPTION 'financial_entitlement_fact_immutable' USING ERRCODE='23514';
END $$;
CREATE TRIGGER financial_entitlement_fact_immutable
BEFORE UPDATE OR DELETE OR TRUNCATE ON financial_client_assessments
FOR EACH STATEMENT EXECUTE FUNCTION financial_entitlement_deny_mutation();
""").execute_if(dialect="postgresql"),
)
