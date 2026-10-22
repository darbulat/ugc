"""Shared PostgreSQL invariants for Alembic and full metadata creation."""

TRIGGER_SQL = """
        CREATE FUNCTION financial_deny_mutation() RETURNS trigger LANGUAGE
                plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'financial_record_immutable' USING ERRCODE =
                '23514';
        END $$;
        CREATE TRIGGER financial_policy_immutable BEFORE UPDATE OR DELETE ON
                financial_policy_versions
            FOR EACH ROW EXECUTE FUNCTION financial_deny_mutation();
        CREATE TRIGGER financial_allocation_immutable BEFORE UPDATE OR DELETE
                ON payment_item_allocations
            FOR EACH ROW EXECUTE FUNCTION financial_deny_mutation();
        CREATE FUNCTION financial_guard_payment() RETURNS trigger LANGUAGE
                plpgsql AS $$
        BEGIN
            IF OLD.captured_minor IS NOT NULL AND (TG_OP = 'DELETE' OR
                (NEW.captured_minor, NEW.currency, NEW.order_id,
                NEW.financial_version, NEW.provider, NEW.external_id)
                IS DISTINCT FROM
                (OLD.captured_minor, OLD.currency, OLD.order_id,
                OLD.financial_version, OLD.provider, OLD.external_id)) THEN
                RAISE EXCEPTION 'allocated_payment_immutable' USING ERRCODE =
                '23514';
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER financial_payment_immutable BEFORE UPDATE OR DELETE ON
                payments
            FOR EACH ROW EXECUTE FUNCTION financial_guard_payment();
        CREATE FUNCTION financial_guard_item_price() RETURNS trigger LANGUAGE
                plpgsql AS $$
        BEGIN
            IF (OLD.captured_at IS NOT NULL OR EXISTS (
                SELECT 1 FROM payment_item_allocations WHERE paid_item_id =
                OLD.paid_item_id
            )) AND (TG_OP = 'DELETE' OR
                (NEW.paid_item_id, NEW.ordinal, NEW.order_id, NEW.currency,
                NEW.selection_minor, NEW.accompaniment_minor,
                 NEW.policy_version, NEW.selection_due_at, NEW.quote_key,
                NEW.quote_payload, NEW.captured_at)
                IS DISTINCT FROM
                (OLD.paid_item_id, OLD.ordinal, OLD.order_id, OLD.currency,
                OLD.selection_minor, OLD.accompaniment_minor,
                 OLD.policy_version, OLD.selection_due_at, OLD.quote_key,
                OLD.quote_payload, OLD.captured_at)) THEN
                RAISE EXCEPTION 'captured_item_immutable' USING ERRCODE =
                '23514';
            END IF;
            IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER financial_item_price_immutable BEFORE UPDATE OR DELETE
                ON order_items
            FOR EACH ROW EXECUTE FUNCTION financial_guard_item_price();
        CREATE FUNCTION financial_check_allocation() RETURNS trigger LANGUAGE
                plpgsql AS $$
        DECLARE captured bigint; allocated bigint; component_limit bigint;
        BEGIN
            SELECT captured_minor INTO captured FROM payments
                WHERE payment_id = NEW.payment_id FOR UPDATE;
            IF captured IS NULL THEN
                RAISE EXCEPTION 'capture_required' USING ERRCODE = '23514';
            END IF;
            SELECT COALESCE(sum(amount_minor), 0) INTO allocated
                FROM payment_item_allocations WHERE payment_id = NEW.payment_id;
            IF allocated + NEW.amount_minor > captured THEN
                RAISE EXCEPTION 'allocation_exceeds_capture' USING ERRCODE =
                '23514';
            END IF;
            SELECT CASE WHEN NEW.component = 'selection' THEN selection_minor
                ELSE accompaniment_minor END
                INTO component_limit FROM order_items WHERE paid_item_id =
                NEW.paid_item_id FOR UPDATE;
            IF NEW.amount_minor > component_limit THEN
                RAISE EXCEPTION 'allocation_exceeds_component' USING ERRCODE =
                '23514';
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER financial_allocation_limit BEFORE INSERT ON
                payment_item_allocations
            FOR EACH ROW EXECUTE FUNCTION financial_check_allocation();
"""
