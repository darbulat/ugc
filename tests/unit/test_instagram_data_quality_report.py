"""Freshness semantics and a CLI that never exposes connection exceptions."""

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from ugc_bot import instagram_data_quality_report as report

NOW = datetime(2026, 11, 20, 8, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "known,date,bound,since,expected",
    [
        (False, NOW, True, None, "missing"),
        (True, NOW, False, None, "identity_mismatch"),
        (True, "invalid", True, None, "invalid_timestamp"),
        (True, None, True, None, "undated"),
        (True, None, True, NOW, "before_current_identity"),
        (True, NOW - timedelta(days=2), True, NOW, "before_current_identity"),
        (True, NOW + timedelta(seconds=1), True, None, "future_timestamp"),
        (True, NOW - timedelta(days=14), True, None, "fresh"),
        (True, NOW - timedelta(days=14, seconds=1), True, None, "stale"),
        (True, NOW.isoformat(), True, NOW, "fresh"),
        (True, NOW.replace(tzinfo=None), True, None, "fresh"),
    ],
)
def test_field_state(known, date, bound, since, expected):
    assert (
        report.field_state(
            known, date, at=NOW, days=14, bound=bound, since=since
        )
        == expected
    )


@pytest.mark.parametrize(
    "dialect,context,at,days",
    [
        ("sqlite", "context", NOW, 14),
        ("postgresql", " ", NOW, 14),
        ("postgresql", "context", NOW.replace(tzinfo=None), 14),
        ("postgresql", "context", NOW, 0),
        ("postgresql", "context", NOW, 366),
    ],
)
def test_report_rejects_unsafe_or_ambiguous_inputs(dialect, context, at, days):
    engine = SimpleNamespace(
        dialect=SimpleNamespace(name=dialect), connect=Mock()
    )
    with pytest.raises(ValueError):
        report.collect_report(engine, context, at=at, days=days)
    engine.connect.assert_not_called()


def test_cli_emits_aggregate_json_and_disposes_engine(monkeypatch, capsys):
    engine = Mock()
    build = Mock(return_value={"totals": {"profiles": 4}})
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://unused")
    monkeypatch.setenv("INSTAGRAM_IDENTITY_CONTEXT", "context")
    monkeypatch.setattr(report.sa, "create_engine", Mock(return_value=engine))
    monkeypatch.setattr(report, "collect_report", build)
    assert report.main(["--fresh-days", "30"]) == 0
    assert json.loads(capsys.readouterr().out) == {"totals": {"profiles": 4}}
    assert build.call_args.kwargs["days"] == 30
    engine.dispose.assert_called_once()


@pytest.mark.parametrize("creation_fails", [False, True])
def test_cli_never_prints_credentials_from_errors(
    monkeypatch, capsys, creation_fails
):
    engine = Mock()
    factory = Mock(
        side_effect=ValueError("private-secret") if creation_fails else None,
        return_value=engine,
    )
    monkeypatch.setenv("DATABASE_URL", "private-secret")
    monkeypatch.setenv("INSTAGRAM_IDENTITY_CONTEXT", "context")
    monkeypatch.setattr(report.sa, "create_engine", factory)
    monkeypatch.setattr(
        report,
        "collect_report",
        Mock(side_effect=RuntimeError("private-secret")),
    )
    assert report.main([]) == 1
    captured = capsys.readouterr()
    assert "private-secret" not in captured.out + captured.err
    assert "Data quality report failed" in captured.err
    assert engine.dispose.call_count == (0 if creation_fails else 1)
