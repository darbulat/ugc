"""Malformed URL parser failures cannot fall back to unredacted credentials."""

import pytest

from tests.unit.test_startup_logging_redaction import emitted_config


@pytest.mark.parametrize("json_mode", [False, True])
@pytest.mark.parametrize("prefix", [" ", "\x00", "\n"])
def test_malformed_network_paths_with_leading_controls_are_masked(
    prefix: str, json_mode: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    rendered, safe = emitted_config(
        {
            "endpoint": prefix
            + "//synthetic-c0-user:synthetic-c0-password@[invalid",
            "public_label": "ordinary label [not a URL",
        },
        json_mode=json_mode,
        monkeypatch=monkeypatch,
    )
    assert "synthetic-c0-user" not in rendered
    assert "synthetic-c0-password" not in rendered
    assert safe["endpoint"] == "***"
    assert safe["public_label"] == "ordinary label [not a URL"
