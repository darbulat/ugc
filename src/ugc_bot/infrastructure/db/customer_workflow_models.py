"""Operational request/outbox and followup persistence.

without financial FKs."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from ugc_bot.infrastructure.db.base import Base

metadata = Base.metadata
REQUESTS = sa.Table(
    "customer_requests",
    metadata,
    sa.Column("request_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("user_id", UUID(as_uuid=True), nullable=False),
    sa.Column("order_id", UUID(as_uuid=True)),
    sa.Column("kind", sa.String(20), nullable=False),
    sa.Column("operation_key", sa.String(256), nullable=False),
    sa.Column("payload_hash", sa.String(64), nullable=False),
    sa.Column(
        "payload", sa.JSON().with_variant(JSONB(), "postgresql"), nullable=False
    ),
    sa.Column("state", sa.String(20), nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("expanded_at", sa.DateTime(timezone=True)),
    sa.UniqueConstraint("user_id", "kind", "operation_key"),
    sa.CheckConstraint("state in ('new','in_progress','resolved')"),
    sa.CheckConstraint("kind in ('support','service')"),
)
SERIES = sa.Table(
    "client_followup_series",
    metadata,
    sa.Column("series_id", UUID(as_uuid=True), primary_key=True),
    sa.Column("user_id", UUID(as_uuid=True), nullable=False, unique=True),
    sa.Column("generation", sa.Integer, nullable=False),
    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("last_activity_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("order_id", UUID(as_uuid=True)),
    sa.Column("channel", sa.String(20)),
    sa.Column("opted_out", sa.Boolean, nullable=False),
    sa.Column("stop_reason", sa.String(30)),
)
JOBS = sa.Table(
    "customer_workflow_deliveries",
    metadata,
    sa.Column("job_id", UUID(as_uuid=True), primary_key=True),
    sa.Column(
        "request_id",
        UUID(as_uuid=True),
        sa.ForeignKey("customer_requests.request_id"),
    ),
    sa.Column(
        "series_id",
        UUID(as_uuid=True),
        sa.ForeignKey("client_followup_series.series_id"),
    ),
    sa.Column("recipient_id", UUID(as_uuid=True), nullable=False),
    sa.Column("stage", sa.Integer),
    sa.Column("part", sa.Integer, nullable=False, server_default="0"),
    sa.Column("text", sa.Text),
    sa.Column("generation", sa.Integer),
    sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("state", sa.String(20), nullable=False),
    sa.Column("lease_token", UUID(as_uuid=True)),
    sa.Column("lease_until", sa.DateTime(timezone=True)),
    sa.Column("provider_reference", sa.String(500)),
    sa.Column("reason", sa.String(200)),
    sa.UniqueConstraint("series_id", "stage"),
    sa.UniqueConstraint("request_id", "recipient_id", "part"),
    sa.CheckConstraint(
        "state in ('ready','leased','sending','accepted',"
        "'failed','unknown','obsolete')"
    ),
    sa.CheckConstraint("(request_id is null) <> (series_id is null)"),
    sa.CheckConstraint("stage is null or stage between 1 and 3"),
    sa.Index("ix_customer_delivery_due", "state", "due_at"),
)
TABLES = (REQUESTS, SERIES, JOBS)
