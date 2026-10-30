"""Allow explicitly public policies in correction authority checks."""

from importlib import import_module

import sqlalchemy as sa
from alembic import op

revision = "0127_public_policy_scope"
down_revision = "0126_followup_new_orders"
branch_labels = None
depends_on = None

POLICY_ALLOWED_SQL = """COALESCE(
  (policy.rules->'all_clients' = 'true'::jsonb
   AND policy.rules->'allowed_clients' = '[]'::jsonb)
  OR ((NOT (policy.rules ? 'all_clients')
       OR policy.rules->'all_clients' = 'false'::jsonb)
      AND jsonb_typeof(policy.rules->'allowed_clients') = 'array'
      AND NOT EXISTS (
          SELECT 1 FROM jsonb_array_elements(
              CASE WHEN jsonb_typeof(policy.rules->'allowed_clients') = 'array'
                   THEN policy.rules->'allowed_clients' ELSE '[]'::jsonb END
          ) AS client(value)
          WHERE jsonb_typeof(client.value) <> 'string'
             OR client.value #>> '{}' !~*
                 ('^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-' ||
                  '[0-9a-f]{4}-[0-9a-f]{12}$')
             OR client.value #>> '{}' = '00000000-0000-0000-0000-000000000000'
      )
      AND policy.rules->'allowed_clients' @>
          to_jsonb(ARRAY[request.client_id::text])), false)"""


def _authority_sql(*, public: bool) -> str:
    # Preserve the deployed 0120 function byte-for-byte apart from the single
    # access predicate; the older schema builder is not the deployed version.
    source = import_module(
        "ugc_bot.infrastructure.db.migrations.versions.0120_variable_tariff"
    ).UPGRADE_SQL
    start = source.index(
        "CREATE OR REPLACE FUNCTION "
        "correction_validate_authority(authority jsonb)"
    )
    end = source.index("END $$;", start) + len("END $$;")
    function = source[start:end]
    old = """OR NOT COALESCE(policy.rules->'allowed_clients' @>
 to_jsonb(ARRAY[request.client_id::text]),false)"""
    new = "OR NOT " + POLICY_ALLOWED_SQL
    if function.count(old) != 1:
        raise RuntimeError("unexpected_correction_authority_definition")
    return function.replace(old, new) if public else function


def upgrade() -> None:
    op.execute(sa.text(_authority_sql(public=True)))


def downgrade() -> None:
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 FROM financial_policy_versions "
                "WHERE rules->'all_clients' = 'true'::jsonb LIMIT 1"
            )
        )
        .first()
    ):
        raise RuntimeError("Cannot downgrade while public policies exist")
    op.execute(sa.text(_authority_sql(public=False)))
