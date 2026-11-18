"""Manual contact handoffs, independent of paid positions and settlement."""

import sqlalchemy as sa

from ugc_bot.infrastructure.db.base import Base


def transfer_table(metadata):
    return sa.Table(
        "order_creator_transfers",
        metadata,
        sa.Column("transfer_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "order_id",
            sa.Uuid(),
            sa.ForeignKey("orders.order_id"),
            nullable=False,
        ),
        sa.Column(
            "creator_id",
            sa.Uuid(),
            sa.ForeignKey("users.user_id"),
            nullable=False,
        ),
        sa.Column(
            "client_id",
            sa.Uuid(),
            sa.ForeignKey("users.user_id"),
            nullable=False,
        ),
        sa.Column("operator", sa.String(200), nullable=False),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("state", sa.String(30), nullable=False),
        sa.Column("attempt_token", sa.Uuid(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("contact", sa.JSON(), nullable=False),
        sa.Column("requested_price", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("provider_reference", sa.String(200)),
        sa.Column("last_error", sa.String(200)),
        sa.Column("feedback", sa.String(30)),
        sa.Column("feedback_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "order_id", "creator_id", name="uq_order_creator_transfer"
        ),
        sa.UniqueConstraint(
            "client_id",
            "provider_reference",
            name="uq_creator_transfer_receipt",
        ),
        sa.CheckConstraint(
            "source IN ('reserve','counteroffer')",
            name="ck_creator_transfer_source",
        ),
        sa.CheckConstraint(
            "state IN ('sending','sent','failed','unknown')",
            name="ck_creator_transfer_state",
        ),
        sa.CheckConstraint(
            "(state='sent' AND sent_at IS NOT NULL "
            "AND provider_reference IS NOT NULL) "
            "OR (state<>'sent' AND sent_at IS NULL "
            "AND provider_reference IS NULL)",
            name="ck_creator_transfer_receipt",
        ),
        sa.CheckConstraint(
            "requested_price>=0 AND client_id<>creator_id",
            name="ck_creator_transfer_parties",
        ),
        sa.CheckConstraint(
            "feedback IS NULL OR (state='sent' "
            "AND feedback IN ('worked','not_worked','not_agreed'))",
            name="ck_creator_transfer_feedback",
        ),
    )


TRANSFERS = transfer_table(Base.metadata)

# Sent contact snapshots survive assignment/profile changes and order closure.
GUARD_SQL = """
CREATE OR REPLACE FUNCTION creator_transfer_preserve_history()
RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
 IF TG_OP <> 'UPDATE' THEN
  RAISE EXCEPTION 'creator_transfer_history_required' USING ERRCODE='23514';
 END IF;
 IF (NEW.transfer_id,NEW.order_id,NEW.creator_id,NEW.client_id)
    IS DISTINCT FROM
    (OLD.transfer_id,OLD.order_id,OLD.creator_id,OLD.client_id)
    OR (OLD.state='sent' AND
      (to_jsonb(NEW)-'feedback'-'feedback_at') IS DISTINCT FROM
      (to_jsonb(OLD)-'feedback'-'feedback_at')) THEN
  RAISE EXCEPTION 'creator_transfer_history_immutable' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER creator_transfer_preserve_row
 BEFORE UPDATE OR DELETE ON order_creator_transfers
 FOR EACH ROW EXECUTE FUNCTION creator_transfer_preserve_history();
CREATE TRIGGER creator_transfer_preserve_table
 BEFORE TRUNCATE ON order_creator_transfers
 FOR EACH STATEMENT EXECUTE FUNCTION creator_transfer_preserve_history();
"""
sa.event.listen(
    TRANSFERS,
    "after_create",
    sa.DDL(GUARD_SQL).execute_if(dialect="postgresql"),
)
