"""The policy command previews by default and only publishes explicitly."""

import importlib
import importlib.util
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from tests.application.services.test_refund_policy_publication import config


def module():
    name = "ugc_bot.financial_policy_config"
    assert importlib.util.find_spec(name) is not None, (
        "No executable environment-policy configuration command"
    )
    return importlib.import_module(name)


def arguments():
    return [
        "--version",
        "refund-config-test",
        "--approved-by",
        str(uuid4()),
        "--effective-from",
        "2027-01-01T00:00:00+00:00",
        "--terms-reference",
        "terms:synthetic:refund-config",
        "--allowed-client",
        str(uuid4()),
    ]


def test_preview_loads_environment_rules_without_connecting_to_database(
    monkeypatch, capsys
):
    command = module()
    monkeypatch.setattr(
        command, "load_config", lambda: SimpleNamespace(financial=config())
    )

    async def forbidden(*args):
        pytest.fail("Preview attempted to publish")

    monkeypatch.setattr(command, "_publish", forbidden)
    assert command.main(arguments()) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["published"] is False
    assert result["refund_window_seconds"] == 604800
    assert "approved_at" not in result


def test_explicit_publish_passes_same_frozen_draft_and_actor(
    monkeypatch, capsys
):
    command = module()
    monkeypatch.setattr(
        command, "load_config", lambda: SimpleNamespace(financial=config())
    )
    calls = []

    async def publish(cfg, draft, actor):
        calls.append((draft, actor))
        return SimpleNamespace(approved_at=draft.effective_from)

    monkeypatch.setattr(command, "_publish", publish)
    args = arguments()
    assert command.main(args + ["--publish"]) == 0
    assert len(calls) == 1
    assert str(calls[0][1]) == args[args.index("--approved-by") + 1]
    result = json.loads(capsys.readouterr().out)
    assert result["published"] is True
    assert result["approved_at"] == "2027-01-01T00:00:00+00:00"


def test_multiple_explicit_allowlisted_clients_survive_preview(
    monkeypatch, capsys
):
    command = module()
    monkeypatch.setattr(
        command, "load_config", lambda: SimpleNamespace(financial=config())
    )
    extra = str(uuid4())
    assert command.main(arguments() + ["--allowed-client", extra]) == 0
    result = json.loads(capsys.readouterr().out)
    assert len(result["allowed_clients"]) == 2
    assert extra in result["allowed_clients"]


@pytest.mark.parametrize("failure", ["config", "permission", "conflict"])
def test_command_errors_are_explicit_and_do_not_expose_config_or_sources(
    monkeypatch, capsys, failure
):
    command = module()

    def load():
        if failure == "config":
            raise ValueError("private value must not leak")
        return SimpleNamespace(financial=config())

    async def publish(*args):
        if failure == "permission":
            raise PermissionError("private role snapshot must not leak")
        raise ValueError("private changed terms must not leak")

    monkeypatch.setattr(command, "load_config", load)
    monkeypatch.setattr(command, "_publish", publish)
    with pytest.raises(SystemExit) as error:
        command.main(arguments() + ["--publish"])
    assert error.value.code == 2
    output = capsys.readouterr()
    assert not output.out and "private" not in output.err


@pytest.mark.asyncio
async def test_publish_without_database_refuses_and_disposes_container(
    monkeypatch,
):
    command = module()
    import ugc_bot.container
    from tests.application.services.test_refund_policy_publication import inputs
    from ugc_bot.application.services.financial_policy_publication import (
        FinancialPolicyDraft,
    )

    disposed = []

    class NoDatabase:
        transaction_manager = None

        def __init__(self, cfg):
            pass

        async def dispose(self):
            disposed.append(True)

    monkeypatch.setattr(ugc_bot.container, "Container", NoDatabase)
    draft = FinancialPolicyDraft.from_environment(config(), **inputs())
    with pytest.raises(ValueError, match="policy_database_required"):
        await command._publish(SimpleNamespace(), draft, uuid4())
    assert disposed == [True]
