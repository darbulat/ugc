"""Install the same receipt guards for Alembic and full metadata."""

from ugc_bot.infrastructure.db.invite_handoff_models import (
    NOTICES,
    SHARING,
    STAFF_DELIVERIES,
    VISITS,
)
from ugc_bot.infrastructure.db.selection_maturity_schema import (
    PER_ITEM_SELECTION_SOURCE_GUARD,
)

FIRST_CONTACT = """
CREATE OR REPLACE VIEW order_first_selection_contacts AS
SELECT DISTINCT ON (paid_item_id)
  paid_item_id, delivery_id, order_id, payment_id, client_id, accepted_at
FROM (
  SELECT paid_item_id, delivery_id, order_id, payment_id, client_id, accepted_at
  FROM paid_selection_accepted_deliveries
  UNION ALL
  SELECT paid_item_id, delivery_id, order_id, payment_id, client_id, accepted_at
  FROM order_invite_staff_deliveries
) AS contacts
ORDER BY paid_item_id, accepted_at, delivery_id;
"""
STAFF_GUARD = """
CREATE OR REPLACE FUNCTION order_invite_staff_delivery_check() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM order_creator_invites v
    JOIN order_items i ON i.paid_item_id=v.item_id AND i.order_id=v.order_id
    JOIN orders o ON o.order_id=i.order_id
    JOIN payments p ON p.order_id=o.order_id
    WHERE v.id=NEW.delivery_id AND v.item_id=NEW.paid_item_id
      AND v.order_id=NEW.order_id AND v.reported_at <= NEW.accepted_at
      AND v.consented_at IS NULL AND v.telegram IS NOT NULL
      AND o.advertiser_id=NEW.client_id AND o.status='active'
      AND NOT o.complimentary AND o.financial_version IS NOT NULL
      AND p.payment_id=NEW.payment_id AND p.status='paid'
      AND i.captured_at=p.paid_at AND i.selection_state='paid'
      AND NOT EXISTS (
        SELECT 1 FROM item_assignments a WHERE a.paid_item_id=i.paid_item_id
      )
  ) THEN RAISE EXCEPTION 'invite_staff_delivery_scope_invalid'
    USING ERRCODE='23514';
  END IF;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS order_invite_staff_delivery_scope
  ON order_invite_staff_deliveries;
CREATE TRIGGER order_invite_staff_delivery_scope BEFORE INSERT
  ON order_invite_staff_deliveries FOR EACH ROW
  EXECUTE FUNCTION order_invite_staff_delivery_check();
DROP TRIGGER IF EXISTS order_invite_staff_delivery_immutable
  ON order_invite_staff_deliveries;
CREATE TRIGGER order_invite_staff_delivery_immutable
  BEFORE UPDATE OR DELETE OR TRUNCATE ON order_invite_staff_deliveries
  FOR EACH STATEMENT EXECUTE FUNCTION financial_selection_deny_mutation();
"""
TABLES = (SHARING, VISITS, NOTICES, STAFF_DELIVERIES)
NATIVE = "paid_selection_accepted_deliveries"
FIRST = "order_first_selection_contacts"


def rewrite_correction_guard(execute, before, after):
    # Carry forward the installed correction rules, including variable tariffs.
    for name in (
        "correction_validate_authority(jsonb)",
        "correction_check_application()",
    ):
        execute(
            f"""
DO $change$
DECLARE source text := pg_get_functiondef('{name}'::regprocedure);
BEGIN
  IF strpos(source, '{after}') <> 0 THEN
    RETURN;
  END IF;
  IF strpos(source, '{before}') = 0 THEN
    RAISE EXCEPTION 'unexpected correction guard source';
  END IF;
  EXECUTE replace(source, '{before}', '{after}');
END $change$;
"""
        )


def install_invite_handoff_guards(execute):
    execute(FIRST_CONTACT)
    execute(STAFF_GUARD)
    execute(PER_ITEM_SELECTION_SOURCE_GUARD.replace(NATIVE, FIRST))
    rewrite_correction_guard(execute, NATIVE, FIRST)
