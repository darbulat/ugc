"""Frozen Task18 schema shared by migration and full metadata creation.

No financial workflows or legacy decimal conversions live here.
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

NAMES = (
    "financial_wallets",
    "rate_snapshots",
    "financial_obligations",
    "financial_movements",
    "financial_audit_events",
)


def _non_nil_constraints(tables: dict[str, sa.Table]) -> None:
    for name, table in tables.items():
        for column in table.columns:
            if isinstance(column.type, UUID):
                table.append_constraint(
                    sa.CheckConstraint(
                        f"{column.name} IS NULL OR {column.name} <> "
                        "'00000000-0000-0000-0000-000000000000'",
                        name=f"ck_{name}_{column.name}_non_nil",
                    )
                )


def ledger_tables(metadata: sa.MetaData) -> dict[str, sa.Table]:
    def uid(name, target=None, nullable=False, primary_key=False):
        args = [sa.ForeignKey(target)] if target else []
        return sa.Column(
            name,
            UUID(as_uuid=True),
            *args,
            nullable=nullable,
            primary_key=primary_key,
        )

    def col(name, type_=sa.String, nullable=False):
        return sa.Column(name, type_, nullable=nullable)

    def instant(name, nullable=False):
        return col(name, sa.DateTime(timezone=True), nullable)

    def check(expression, name):
        return sa.CheckConstraint(expression, name=name)

    def scope():
        return [
            uid("recipient_id", "users.user_id"),
            uid("paid_item_id"),
            uid("order_id"),
            uid(
                "assignment_id", "item_assignments.assignment_id", nullable=True
            ),
        ]

    tables = {}
    tables["financial_wallets"] = sa.Table(
        "financial_wallets",
        metadata,
        uid("recipient_id", "users.user_id", primary_key=True),
        sa.Column("currency", sa.String(3), primary_key=True),
        *[
            sa.Column(
                name, sa.BigInteger, nullable=False, server_default=sa.text("0")
            )
            for name in (
                "pending_minor",
                "hold_minor",
                "available_minor",
                "reserved_minor",
                "blocked_minor",
                "paid_minor",
                "cancelled_minor",
                "debt_minor",
                "version",
            )
        ],
        check("currency = 'RUB'", "ck_wallet_currency"),
        check(
            " AND ".join(
                f"{name} >= 0"
                for name in (
                    "pending_minor",
                    "hold_minor",
                    "available_minor",
                    "reserved_minor",
                    "blocked_minor",
                    "paid_minor",
                    "cancelled_minor",
                    "debt_minor",
                    "version",
                )
            ),
            "ck_wallet_nonnegative",
        ),
    )
    tables["rate_snapshots"] = sa.Table(
        "rate_snapshots",
        metadata,
        uid("id", primary_key=True),
        *scope(),
        uid("referred_user_id", "users.user_id"),
        uid("payment_id", "payments.payment_id"),
        col("currency", sa.String(3)),
        col("side"),
        instant("effective_at"),
        instant("registered_at"),
        col("age_rule"),
        col("verified_count", sa.BigInteger),
        col("rate_bps", sa.Integer),
        col("policy_version"),
        col("payload_hash", sa.String(64)),
        sa.ForeignKeyConstraint(
            ["policy_version"], ["financial_policy_versions.version"]
        ),
        sa.ForeignKeyConstraint(
            ["paid_item_id", "order_id", "currency"],
            [
                "order_items.paid_item_id",
                "order_items.order_id",
                "order_items.currency",
            ],
        ),
        sa.UniqueConstraint(
            "id",
            "recipient_id",
            "paid_item_id",
            "order_id",
            "policy_version",
            name="uq_snapshot_scope",
        ),
    )
    tables["financial_obligations"] = sa.Table(
        "financial_obligations",
        metadata,
        uid("id", primary_key=True),
        col("business_key"),
        col("kind"),
        *scope(),
        col("currency", sa.String(3)),
        col("base_minor", sa.BigInteger),
        col("amount_minor", sa.BigInteger),
        uid("snapshot_id"),
        col("policy_version"),
        instant("hold_until", True),
        instant("available_at", True),
        instant("recorded_at"),
        col("payload_hash", sa.String(64)),
        sa.UniqueConstraint("business_key", name="uq_obligation_business_key"),
        sa.UniqueConstraint(
            "paid_item_id",
            "recipient_id",
            "kind",
            name="uq_obligation_economic_basis",
        ),
        sa.UniqueConstraint("id", "currency", name="uq_obligation_currency"),
        sa.ForeignKeyConstraint(
            ["paid_item_id", "order_id", "currency"],
            [
                "order_items.paid_item_id",
                "order_items.order_id",
                "order_items.currency",
            ],
        ),
        sa.ForeignKeyConstraint(
            [
                "snapshot_id",
                "recipient_id",
                "paid_item_id",
                "order_id",
                "policy_version",
            ],
            [
                "rate_snapshots.id",
                "rate_snapshots.recipient_id",
                "rate_snapshots.paid_item_id",
                "rate_snapshots.order_id",
                "rate_snapshots.policy_version",
            ],
        ),
        check("base_minor > 0 AND amount_minor > 0", "ck_obligation_positive"),
        check("currency = 'RUB'", "ck_obligation_currency"),
        check(
            "kind IN ('client_referral','creator_referral','management')",
            "ck_obligation_kind",
        ),
    )
    tables["financial_movements"] = sa.Table(
        "financial_movements",
        metadata,
        uid("id", primary_key=True),
        uid("obligation_id"),
        col("operation_key"),
        col("event_id"),
        col("movement_type"),
        col("amount_minor", sa.BigInteger),
        col("currency", sa.String(3)),
        instant("effective_at"),
        instant("recorded_at"),
        uid("actor_id", "users.user_id", True),
        col("actor_kind"),
        col("system_actor", nullable=True),
        col("reason", sa.Text),
        col("bucket_from", nullable=True),
        col("bucket_to", nullable=True),
        uid("source_entry_id", nullable=True),
        uid("request_id", "payout_requests.request_id", True),
        *[
            uid(name, nullable=True)
            for name in (
                "allocation_id",
                "execution_id",
                "refund_id",
                "case_id",
            )
        ],
        col("payload_hash", sa.String(64)),
    )
    tables["financial_audit_events"] = sa.Table(
        "financial_audit_events",
        metadata,
        uid("id", primary_key=True),
        col("operation_key"),
        col("action"),
        col("scope"),
        col("reason", sa.Text),
        uid("actor_id", "users.user_id", True),
        col("actor_kind"),
        col("system_actor", nullable=True),
        uid("obligation_id", "financial_obligations.id", True),
        uid("movement_id", "financial_movements.id", True),
        instant("effective_at"),
        instant("recorded_at"),
        col("payload_hash", sa.String(64)),
        col("details", sa.JSON),
    )
    _non_nil_constraints(tables)
    for name, label in (
        ("rate_snapshots", "snapshot"),
        ("financial_obligations", "obligation"),
    ):
        tables[name].append_constraint(
            sa.ForeignKeyConstraint(
                ["assignment_id", "paid_item_id"],
                [
                    "item_assignments.assignment_id",
                    "item_assignments.paid_item_id",
                ],
                name=f"fk_{label}_assignment_scope",
            )
        )
    rate = tables["rate_snapshots"]
    rate.append_constraint(
        check(
            "rate_bps BETWEEN 0 AND 10000 AND verified_count >= 0",
            "ck_snapshot_rate",
        )
    )
    rate.append_constraint(
        check(
            (
                "side IN ('client','creator','management') AND currency "
                "= 'RUB' AND age_rule IN "
                "('first_year','after_anniversary','management') AND "
                "effective_at >= registered_at"
            ),
            "ck_snapshot_policy",
        )
    )
    rate.append_constraint(
        sa.ForeignKeyConstraint(
            ["payment_id", "order_id", "currency"],
            ["payments.payment_id", "payments.order_id", "payments.currency"],
        )
    )
    movement = tables["financial_movements"]
    movement.append_constraint(
        sa.UniqueConstraint("operation_key", name="uq_movement_operation")
    )
    movement.append_constraint(
        sa.UniqueConstraint(
            "id", "obligation_id", "currency", name="uq_movement_source_scope"
        )
    )
    movement.append_constraint(
        sa.ForeignKeyConstraint(
            ["obligation_id", "currency"],
            ["financial_obligations.id", "financial_obligations.currency"],
        )
    )
    movement.append_constraint(
        sa.ForeignKeyConstraint(
            ["source_entry_id", "obligation_id", "currency"],
            [
                "financial_movements.id",
                "financial_movements.obligation_id",
                "financial_movements.currency",
            ],
        )
    )
    movement.append_constraint(
        check("amount_minor > 0 AND currency = 'RUB'", "ck_movement_money")
    )
    movement.append_constraint(
        check(
            (
                "movement_type IN "
                "('issuance','transfer','reversal','debt','recovery')"
            ),
            "ck_movement_type",
        )
    )
    movement.append_constraint(
        check(
            (
                "movement_type NOT IN ('reversal','debt','recovery') OR "
                "source_entry_id IS NOT NULL"
            ),
            "ck_movement_source",
        )
    )
    movement.append_constraint(
        check(
            "movement_type NOT IN ('debt','recovery') OR case_id IS NOT NULL",
            "ck_movement_case",
        )
    )
    movement.append_constraint(
        check(
            (
                "movement_type <> 'issuance' OR (bucket_from IS NULL AND"
                " bucket_to IS NOT NULL AND bucket_to = 'pending')"
            ),
            "ck_movement_issuance",
        )
    )
    movement.append_constraint(
        check(
            (
                "movement_type <> 'transfer' OR (bucket_from IS NOT NULL"
                " AND bucket_to IS NOT NULL AND bucket_from <> bucket_to"
                " AND bucket_from NOT IN ('paid','cancelled') AND "
                "bucket_to <> 'cancelled')"
            ),
            "ck_movement_transfer",
        )
    )
    movement.append_constraint(
        check(
            (
                "(bucket_from IS NULL OR bucket_from IN ('pending','hold"
                "','available','reserved','blocked','paid','cancelled'))"
                " AND (bucket_to IS NULL OR bucket_to IN ('pending','hol"
                "d','available','reserved','blocked','paid','cancelled')"
                ")"
            ),
            "ck_movement_buckets",
        )
    )
    movement.append_constraint(
        check(
            (
                "movement_type <> 'transfer' OR ((bucket_from <> "
                "'reserved' AND bucket_to NOT IN ('reserved','paid')) OR"
                " (request_id IS NOT NULL AND allocation_id IS NOT "
                "NULL))"
            ),
            "ck_movement_reserve_refs",
        )
    )
    movement.append_constraint(
        check(
            (
                "movement_type <> 'transfer' OR bucket_to <> 'paid' OR "
                "(execution_id IS NOT NULL AND request_id IS NOT NULL "
                "AND allocation_id IS NOT NULL)"
            ),
            "ck_movement_paid_refs",
        )
    )
    for name in ("financial_movements", "financial_audit_events"):
        tables[name].append_constraint(
            check(
                (
                    "(actor_kind IN ('user','admin') AND actor_id IS NOT "
                    "NULL AND actor_id <> "
                    "'00000000-0000-0000-0000-000000000000' AND system_actor"
                    " IS NULL) OR (actor_kind = 'system' AND actor_id IS "
                    "NULL AND system_actor IS NOT NULL AND "
                    "length(trim(system_actor)) > 0)"
                ),
                "ck_" + name + "_actor",
            )
        )
        tables[name].append_constraint(
            check(
                "length(trim(operation_key)) > 0 AND length(trim(reason)) > 0",
                "ck_" + name + "_provenance",
            )
        )
    tables["financial_audit_events"].append_constraint(
        sa.UniqueConstraint(
            "operation_key", name="uq_financial_audit_operation"
        )
    )
    for name in NAMES[1:]:
        tables[name].append_constraint(
            check(
                "payload_hash ~ '^[0-9a-f]{64}$'", "ck_" + name + "_hash"
            ).ddl_if(dialect="postgresql")
        )
    sa.event.listen(
        tables["financial_audit_events"],
        "after_create",
        sa.DDL(IMMUTABILITY_SQL).execute_if(dialect="postgresql"),
    )
    return tables


IMMUTABILITY_SQL = """
CREATE FUNCTION ledger_deny_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 RAISE EXCEPTION 'financial_ledger_immutable' USING ERRCODE='23514';
END $$;
CREATE FUNCTION ledger_check_obligation_scope() RETURNS trigger LANGUAGE
plpgsql AS $$
DECLARE snapshot_side text;
DECLARE snapshot_assignment uuid;
BEGIN
 SELECT side, assignment_id INTO snapshot_side, snapshot_assignment
 FROM rate_snapshots WHERE id=NEW.snapshot_id;
 IF snapshot_assignment IS DISTINCT FROM NEW.assignment_id THEN
  RAISE EXCEPTION 'snapshot_assignment_mismatch' USING ERRCODE='23514';
 END IF;
 IF snapshot_side IS DISTINCT FROM (CASE NEW.kind WHEN 'client_referral' THEN
'client' WHEN 'creator_referral' THEN 'creator' ELSE 'management' END) THEN
  RAISE EXCEPTION 'snapshot_side_mismatch' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER ledger_obligation_scope BEFORE INSERT ON financial_obligations
FOR EACH ROW EXECUTE FUNCTION ledger_check_obligation_scope();
""" + "\n".join(
    (
        f"CREATE TRIGGER ledger_immutable BEFORE UPDATE OR "
        f"DELETE OR TRUNCATE ON {name} FOR EACH STATEMENT "
        f"EXECUTE FUNCTION ledger_deny_mutation();"
    )
    for name in NAMES
    if name != "financial_wallets"
)
