"""Register additive commercial facts without modifying earnings projections."""

import sqlalchemy as sa

from ugc_bot.infrastructure.db.base import Base
from ugc_bot.infrastructure.db.subscription_schema import (
    SUBSCRIPTION_GUARDS,
    subscription_table,
)

SUBSCRIPTIONS = subscription_table(Base.metadata)


def _install_guards(target: sa.Table, connection: sa.Connection, **_) -> None:
    if connection.dialect.name != "postgresql":
        return
    for name in ("subscription_no_mutation", "subscription_authority"):
        connection.exec_driver_sql(
            f"DROP TRIGGER IF EXISTS {name} ON {target.name}"
        )
    connection.exec_driver_sql(SUBSCRIPTION_GUARDS)


sa.event.listen(SUBSCRIPTIONS, "after_create", _install_guards)
