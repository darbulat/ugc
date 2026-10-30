"""Install completed financial guards after the historical metadata hooks.

Partial historical table creation keeps its own guard boundary. Once every
owned source exists, full metadata gets the same guards as the additive
migrations. Repeated create_all must restore that final boundary atomically.
"""


def _drop(connection, table, *triggers):
    for trigger in triggers:
        connection.exec_driver_sql(
            f"DROP TRIGGER IF EXISTS {trigger} ON {table}"
        )


def _install_repayment_guards(connection, names):
    from ugc_bot.infrastructure.db.debt_recovery_models import (
        APPLICATIONS,
        COMMANDS,
        OBSERVATIONS,
    )
    from ugc_bot.infrastructure.db.debt_recovery_schema import (
        debt_recovery_guards,
    )

    tables = {
        COMMANDS.name: (
            "repayment_command_immutable",
            "repayment_command_authority",
        ),
        OBSERVATIONS.name: (
            "repayment_observation_immutable",
            "repayment_observation_source",
        ),
        APPLICATIONS.name: (
            "repayment_application_immutable",
            "repayment_application_source",
        ),
    }
    if not set(tables) <= names:
        return
    for table, triggers in tables.items():
        _drop(connection, table, *triggers)
    connection.exec_driver_sql(debt_recovery_guards())


def install_financial_completion_guards(connection, names):
    from ugc_bot.infrastructure.db.accompaniment_refund_models import (
        TABLES as accompaniment,
    )
    from ugc_bot.infrastructure.db.accompaniment_refund_schema import (
        accompaniment_refund_guards,
    )
    from ugc_bot.infrastructure.db.financial_review_models import (
        TABLES as reviews,
    )
    from ugc_bot.infrastructure.db.financial_review_schema import (
        financial_review_guards,
    )
    from ugc_bot.infrastructure.db.manual_grant_models import TABLES as grants
    from ugc_bot.infrastructure.db.manual_grant_schema import (
        manual_grant_guards,
    )
    from ugc_bot.infrastructure.db.refund_original_models import (
        TABLES as originals,
    )
    from ugc_bot.infrastructure.db.refund_original_schema import (
        refund_original_guards,
    )
    from ugc_bot.infrastructure.db.selection_maturity_models import (
        TABLES as selection,
    )
    from ugc_bot.infrastructure.db.selection_maturity_schema import (
        selection_maturity_guards,
    )

    completion = {
        **selection,
        **{f"accompaniment_{k}": t for k, t in accompaniment.items()},
        **originals,
    }
    if not {t.name for t in completion.values()} <= names:
        return False
    for table in selection.values():
        _drop(
            connection,
            table.name,
            "selection_fact_immutable",
            "selection_source_guard",
        )
    connection.exec_driver_sql(
        selection_maturity_guards(selection, per_item=True)
    )
    for table in accompaniment.values():
        _drop(connection, table.name, "accompaniment_refund_immutable")
    _drop(
        connection,
        accompaniment["applications"].name,
        "accompaniment_refund_application_guard",
    )
    _drop(
        connection,
        accompaniment["management_reviews"].name,
        "accompaniment_management_review_guard",
    )
    connection.exec_driver_sql(accompaniment_refund_guards(accompaniment))
    for table in originals.values():
        _drop(
            connection,
            table.name,
            "refund_original_immutable",
            "refund_original_source_guard",
        )
    connection.exec_driver_sql(refund_original_guards())
    _install_repayment_guards(connection, names)
    if {t.name for t in grants.values()} <= names:
        for table in grants.values():
            _drop(connection, table.name, "manual_grant_immutable")
        _drop(connection, grants["grants"].name, "manual_grant_source_guard")
        _drop(connection, "financial_movements", "manual_grant_movement_guard")
        connection.exec_driver_sql(manual_grant_guards(grants))
    if {t.name for t in reviews.values()} <= names:
        for table in reviews.values():
            _drop(connection, table.name, "financial_review_immutable")
        _drop(
            connection,
            reviews["cases"].name,
            "financial_review_source",
            "financial_review_application",
        )
        _drop(
            connection,
            reviews["resolutions"].name,
            "financial_review_resolution_source",
            "financial_review_resolution_application",
        )
        _drop(
            connection,
            "financial_movements",
            "financial_review_movement_source",
            "financial_review_recovery_source",
        )
        connection.exec_driver_sql(financial_review_guards(reviews))

    return True
