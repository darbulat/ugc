"""A blank optional physical source grants no configured bank namespace."""

import pytest
from pydantic import ValidationError

from ugc_bot.config import AppConfig, FinancialConfig


def test_source_defaults_blank_without_enabling_money(monkeypatch):
    monkeypatch.delenv("FINANCIAL_MANUAL_BANK_SOURCE_ID", raising=False)
    config = FinancialConfig(_env_file=None)
    assert config.manual_bank_source_id == ""
    assert not config.core_enabled and not config.payouts_enabled


def test_source_flat_nested_and_environment_are_explicit(monkeypatch):
    values = {"FINANCIAL_MANUAL_BANK_SOURCE_ID": "synthetic:bank-source"}
    section = FinancialConfig.model_validate(values)
    flat = AppConfig.model_validate({"BOT_TOKEN": "test-token", **values})
    assert section.manual_bank_source_id == "synthetic:bank-source"
    assert flat.financial.manual_bank_source_id == section.manual_bank_source_id
    monkeypatch.setenv(
        "FINANCIAL_MANUAL_BANK_SOURCE_ID", "synthetic:env-source"
    )
    assert (
        FinancialConfig(_env_file=None).manual_bank_source_id
        == "synthetic:env-source"
    )


@pytest.mark.parametrize("length", [256, 257])
def test_source_configuration_has_no_oversize_bypass(length):
    if length == 257:
        with pytest.raises(ValidationError):
            FinancialConfig.model_validate(
                {"FINANCIAL_MANUAL_BANK_SOURCE_ID": "x" * length}
            )
    else:
        assert (
            FinancialConfig.model_validate(
                {"FINANCIAL_MANUAL_BANK_SOURCE_ID": "x" * length}
            ).manual_bank_source_id
            == "x" * length
        )
