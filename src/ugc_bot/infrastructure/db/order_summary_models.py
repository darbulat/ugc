"""Telegram order cards, exception reports and single-attempt notifications."""

import sqlalchemy as sa

from ugc_bot.infrastructure.db.base import Base


def summary_tables(metadata):
    cards = sa.Table(
        "telegram_order_summaries",
        metadata,
        sa.Column(
            "order_id",
            sa.Uuid(),
            sa.ForeignKey("orders.order_id"),
            primary_key=True,
        ),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("draft_id", sa.Uuid()),
        sa.Column("draft", sa.JSON(), nullable=False),
        sa.Column("message_id", sa.String(40)),
        sa.Column("message_claimed_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("responded_at", sa.DateTime(timezone=True)),
        sa.Column("completion_notified_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("draft_id"),
    )
    reports = sa.Table(
        "telegram_order_exceptions",
        metadata,
        sa.Column("report_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "order_id",
            sa.Uuid(),
            sa.ForeignKey("orders.order_id"),
            nullable=False,
        ),
        sa.Column(
            "assignment_id",
            sa.Uuid(),
            sa.ForeignKey("item_assignments.assignment_id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("paid_item_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.Uuid(), nullable=False),
        sa.Column("creator_id", sa.Uuid(), nullable=False),
        sa.Column("reason", sa.String(30), nullable=False),
        sa.Column("state", sa.String(30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("answer_due_at", sa.DateTime(timezone=True)),
        sa.Column("answered_at", sa.DateTime(timezone=True)),
        sa.Column("replacement_id", sa.Uuid()),
        sa.Column("automatic_request_id", sa.Uuid(), unique=True),
        sa.Column("review_reason", sa.String(150)),
        sa.Column("support_request_id", sa.Uuid()),
        sa.CheckConstraint(
            "reason IN ('no_answer','refused','not_done','other')"
        ),
        sa.CheckConstraint(
            "state IN ('queued','waiting','answered','withdrawn',"
            "'review','replaced')"
        ),
        sa.Index("ix_telegram_exception_due", "state", "answer_due_at"),
    )
    jobs = sa.Table(
        "telegram_order_summary_jobs",
        metadata,
        sa.Column("job_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "order_id",
            sa.Uuid(),
            sa.ForeignKey("orders.order_id"),
            nullable=False,
        ),
        sa.Column("report_id", sa.Uuid(), sa.ForeignKey(reports.c.report_id)),
        sa.Column("recipient_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("provider_reference", sa.String(100)),
        sa.Column("delivered_at", sa.DateTime(timezone=True)),
        sa.Column(
            "requested", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.CheckConstraint(
            "(state='sent' AND delivered_at IS NOT NULL "
            "AND provider_reference IS NOT NULL) OR (state<>'sent' "
            "AND delivered_at IS NULL AND provider_reference IS NULL)"
        ),
        sa.CheckConstraint("kind IN ('summary','reminder','creator')"),
        sa.CheckConstraint(
            "state IN ('ready','sending','sent','failed','unknown','obsolete')"
        ),
        sa.CheckConstraint("(kind='creator')=(report_id IS NOT NULL)"),
        sa.Index("ix_telegram_summary_job_due", "state", "due_at"),
    )
    return cards, reports, jobs


CARDS, REPORTS, JOBS = summary_tables(Base.metadata)
