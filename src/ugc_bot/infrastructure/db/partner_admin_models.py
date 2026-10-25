"""Register audited lead decisions and explicit referral-binding corrections."""

import sqlalchemy as sa

from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.partner_admin_schema import (
    binding_table,
    install_immutability,
    review_table,
)

LEAD_REVIEWS = review_table(Base.metadata)
BINDING_CORRECTIONS = binding_table(Base.metadata)


def _install_guards(target: sa.Table, connection: sa.Connection, **_) -> None:
    if connection.dialect.name != "postgresql":
        return
    connection.exec_driver_sql(
        f"DROP TRIGGER IF EXISTS partner_admin_immutable ON {target.name}"
    )
    install_immutability(connection, target)


for table in (LEAD_REVIEWS, BINDING_CORRECTIONS):
    sa.event.listen(table, "after_create", _install_guards)
