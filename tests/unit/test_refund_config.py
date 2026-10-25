"""Explicit refund settings cannot invent or silently coerce financial rules."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from ugc_bot.config import AppConfig, FinancialConfig

WINDOW = "FINANCIAL_SELECTION_REFUND_WINDOW_SECONDS"
ANCHOR = "FINANCIAL_SELECTION_REFUND_WINDOW_ANCHOR"
CLOSURE = "FINANCIAL_SELECTION_CLOSURE_MODE"
RATES = "FINANCIAL_ACCOMPANIMENT_REFUND_RATES_BPS"
MANAGER = "FINANCIAL_ACCOMPANIMENT_MANAGER_REFUND_MODE"
ALIASES = (WINDOW, ANCHOR, CLOSURE, RATES, MANAGER)


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    for alias in (
        *ALIASES,
        "FINANCIAL_CORE_ENABLED",
        "FINANCIAL_PAYOUTS_ENABLED",
    ):
        monkeypatch.delenv(alias, raising=False)


def configured(**changes):
    values = {
        WINDOW: 172800,
        ANCHOR: "item_delivered",
        CLOSURE: "all_positions_resolved",
        RATES: {"success_final": 0, "assigned": 10000},
        MANAGER: "retain_earned",
    }
    return values | changes


def test_unset_rules_preserve_existing_policy_without_enabling_money():
    config = FinancialConfig(_env_file=None)
    assert config.refund_rules() is None
    assert not config.core_enabled and not config.payouts_enabled


def test_refund_document_is_identical_for_flat_nested_and_environment(
    monkeypatch,
):
    values = configured()
    expected = {
        "schema_version": 1,
        "selection_refund_window_seconds": 172800,
        "selection_refund_window_anchor": "item_delivered",
        "selection_closure_mode": "all_positions_resolved",
        "accompaniment_refund_rates_bps": {
            "assigned": 10000,
            "success_final": 0,
        },
        "accompaniment_manager_refund_mode": "retain_earned",
    }
    section = FinancialConfig.model_validate(values)
    flat = AppConfig.model_validate({"BOT_TOKEN": "test-token", **values})
    nested_values = AppConfig.model_validate(
        {"BOT_TOKEN": "test-token"}
    ).model_dump(by_alias=True)
    nested_values["financial"] = values
    nested = AppConfig.model_validate(nested_values)
    for alias, value in values.items():
        monkeypatch.setenv(
            alias, json.dumps(value) if alias == RATES else str(value)
        )
    environment = FinancialConfig(_env_file=None)

    for config in (section, flat.financial, nested.financial, environment):
        rules = config.refund_rules()
        assert rules is not None
        assert rules.to_document() == expected
        assert rules.accompaniment_refund_rates_bps == (
            ("assigned", 10000),
            ("success_final", 0),
        )


@pytest.mark.parametrize("missing", ALIASES)
def test_partial_configuration_is_rejected_at_load(missing):
    values = configured()
    del values[missing]
    with pytest.raises(
        ValidationError, match="refund_rules_configuration_incomplete"
    ):
        FinancialConfig.model_validate(values)


@pytest.mark.parametrize("only", ALIASES)
def test_single_setting_is_not_accepted_as_an_implicit_default(only):
    with pytest.raises(
        ValidationError, match="refund_rules_configuration_incomplete"
    ):
        FinancialConfig.model_validate({only: configured()[only]})


@pytest.mark.parametrize(
    "value", [True, False, 1.0, 1.5, "1.0", "1.5", "1e3", "", 0, -1, 31536001]
)
def test_window_rejects_boolean_fractional_empty_and_out_of_range(value):
    with pytest.raises(ValidationError):
        FinancialConfig.model_validate(configured(**{WINDOW: value}))


@pytest.mark.parametrize("value", [1, "1", 31536000, "31536000"])
def test_window_accepts_integer_environment_values_at_both_limits(value):
    rules = FinancialConfig.model_validate(
        configured(**{WINDOW: value})
    ).refund_rules()
    assert rules is not None
    assert rules.selection_refund_window_seconds == int(value)


@pytest.mark.parametrize(
    "alias,value",
    [
        (ANCHOR, "paid_at"),
        (ANCHOR, ""),
        (CLOSURE, "automatic"),
        (MANAGER, "deduct"),
    ],
)
def test_unknown_decision_modes_are_rejected(alias, value):
    with pytest.raises(ValidationError):
        FinancialConfig.model_validate(configured(**{alias: value}))


@pytest.mark.parametrize(
    "value",
    [
        "{",
        "null",
        "[]",
        "true",
        '{"assigned": true}',
        '{"assigned": 1.0}',
        '{"assigned": "10000"}',
        '{"assigned": NaN}',
        '{"assigned": 5000, "assigned": 10000}',
        {"assigned": True},
        {"assigned": 1.5},
        {"assigned": -1},
        {"assigned": 10001},
        {"unknown_stage": 10000},
        {"disputed": 10000},
        {1: 10000},
    ],
)
def test_refund_rates_reject_malformed_ambiguous_and_unsafe_inputs(value):
    with pytest.raises(ValidationError):
        FinancialConfig.model_validate(configured(**{RATES: value}))


@pytest.mark.parametrize("rates", [{}, "{}"])
def test_explicit_empty_rates_preserve_manual_assessment_for_every_stage(rates):
    rules = FinancialConfig.model_validate(
        configured(**{RATES: rates})
    ).refund_rules()
    assert rules is not None
    assert rules.accompaniment_refund_rates_bps == ()
    assert rules.to_document()["accompaniment_refund_rates_bps"] == {}


def test_environment_is_rejected_instead_of_rounding_a_fractional_window(
    monkeypatch,
):
    for alias, value in configured().items():
        monkeypatch.setenv(
            alias, json.dumps(value) if alias == RATES else str(value)
        )
    monkeypatch.setenv(WINDOW, "172800.5")
    with pytest.raises(ValidationError):
        FinancialConfig(_env_file=None)


def test_settings_without_optional_decode_marker_preserve_strict_env_loading():
    """The settings floor has no NoDecode export or predecode bypass."""
    root = Path(__file__).resolve().parents[2]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = os.pathsep.join(
        (str(root / "src"), str(root), environment.get("PYTHONPATH", ""))
    )
    for alias, value in configured().items():
        environment[alias] = json.dumps(value) if alias == RATES else str(value)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import os
import pydantic_settings
vars(pydantic_settings).pop("NoDecode", None)
from pydantic import ValidationError
from ugc_bot.config import FinancialConfig

rules = FinancialConfig(_env_file=None).refund_rules()
assert rules is not None
assert rules.to_document()["accompaniment_refund_rates_bps"] == {
    "assigned": 10000, "success_final": 0,
}
os.environ["FINANCIAL_ACCOMPANIMENT_REFUND_RATES_BPS"] = (
    '{"assigned":5000,"assigned":10000}'
)
try:
    FinancialConfig(_env_file=None)
except ValidationError:
    pass
else:
    raise AssertionError("Duplicate refund-stage keys were silently decoded")
""",
        ],
        cwd=root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=4,
    )
    assert result.returncode == 0, result.stderr
