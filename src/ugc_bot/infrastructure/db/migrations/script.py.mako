"""${message}"""

from alembic import op
import sqlalchemy as sa

${imports if imports else ""}

revision = ${repr(revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    """Upgrade database schema."""

    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    """Downgrade database schema."""

    ${downgrades if downgrades else "pass"}
