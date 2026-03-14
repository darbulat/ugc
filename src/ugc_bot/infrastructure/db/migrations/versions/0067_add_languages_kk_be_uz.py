"""Add Kazakh, Belarusian, Uzbek to languages table."""

import sqlalchemy as sa
from alembic import op

revision = "0067_add_languages_kk_be_uz"
down_revision = "0066_languages"
branch_labels = None
depends_on = None

_NEW_LANGUAGES = [
    ("kk", "Қазақша"),
    ("be", "Беларуская"),
    ("uz", "O'zbek"),
]


def upgrade() -> None:
    """Insert kk, be, uz into languages table."""
    conn = op.get_bind()
    for code, name in _NEW_LANGUAGES:
        conn.execute(
            sa.text(
                "INSERT INTO languages (code, name_native, enabled) "
                "VALUES (:code, :name, true) ON CONFLICT DO NOTHING"
            ),
            {"code": code, "name": name},
        )


def downgrade() -> None:
    """Remove kk, be, uz from languages table."""
    conn = op.get_bind()
    for code, _ in _NEW_LANGUAGES:
        conn.execute(
            sa.text("DELETE FROM languages WHERE code = :code"),
            {"code": code},
        )
