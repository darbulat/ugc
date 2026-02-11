"""Prevent inserting user_referral_pending when user already has a binding.

Adds a trigger so that if user_id already exists in user_referral_bindings
as referred_user_id, INSERT into user_referral_pending is rejected.
Fixes duplicates when a user opens a referral link again after registration.
"""

from alembic import op

revision = "0035_referral_pending_no_duplicate_binding"
down_revision = "0034_drop_fsm_drafts"
branch_labels = None
depends_on = None

_TRIGGER_NAME = "tr_user_referral_pending_no_duplicate_binding"
_FUNCTION_NAME = "check_no_pending_if_already_bound"


def upgrade() -> None:
    """Create trigger to reject pending when user already has binding."""
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION {_FUNCTION_NAME}()
        RETURNS TRIGGER AS $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM user_referral_bindings
                WHERE referred_user_id = NEW.user_id
            ) THEN
                RAISE EXCEPTION
                    'Pending not allowed: user_id % already has binding',
                    NEW.user_id;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        f"""
        CREATE TRIGGER {_TRIGGER_NAME}
        BEFORE INSERT ON user_referral_pending
        FOR EACH ROW
        EXECUTE FUNCTION {_FUNCTION_NAME}()
        """
    )


def downgrade() -> None:
    """Drop trigger and function."""
    op.execute(
        f"DROP TRIGGER IF EXISTS {_TRIGGER_NAME} ON user_referral_pending"
    )
    op.execute(f"DROP FUNCTION IF EXISTS {_FUNCTION_NAME}()")
