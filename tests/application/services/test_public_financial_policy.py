"""A public policy is explicit, immutable, and keeps old pilots restricted."""

import json
from dataclasses import replace
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from tests.application.services.test_financial_policy_service import (
    ready_policy,
)
from tests.application.services.test_refund_policy_publication import (
    Clock,
    Repository,
    Transactions,
    classes,
    config,
    inputs,
)
from ugc_bot.infrastructure.db.repositories.financial_policy import (
    decode_policy_version,
)


def test_public_gate_allows_new_clients_but_legacy_whitelist_does_not():
    gate, pilot, args = ready_policy()
    args["client_id"] = uuid4()
    with pytest.raises(ValueError, match="client_not_allowlisted"):
        gate.validate_for_capture(**args)
    public = replace(pilot, allowed_clients=frozenset(), all_clients=True)
    args["policy"] = public
    assert gate.validate_for_capture(**args) is public
    args["client_id"] = UUID(int=0)
    with pytest.raises(ValueError, match="client_identity_required"):
        gate.validate_for_capture(**args)


@pytest.mark.parametrize("bad", ["true", 1, None, [], {}])
def test_public_access_requires_exact_boolean(bad):
    _, pilot, _ = ready_policy()
    with pytest.raises(ValueError):
        replace(pilot, all_clients=bad)
    draft, _ = classes()
    with pytest.raises(ValueError):
        draft.from_environment(config(), **(inputs() | {"all_clients": bad}))


def test_decoder_keeps_legacy_restricted_and_rejects_invalid_scope():
    _, pilot, args = ready_policy()
    model = SimpleNamespace(
        version=pilot.version,
        approved_by=pilot.approved_by,
        approved_at=pilot.approved_at,
        effective_from=pilot.effective_from,
        refund_window_seconds=604800,
        rules={
            "allowed_clients": [str(args["client_id"])],
            "terms_reference": pilot.terms_reference,
        },
    )
    assert not decode_policy_version(model).all_clients
    model.rules["allowed_clients"] = []
    model.rules["all_clients"] = True
    assert decode_policy_version(model).allows_client(uuid4())
    model.rules["all_clients"] = "true"
    with pytest.raises(ValueError, match="invalid_policy_document"):
        decode_policy_version(model)


@pytest.mark.asyncio
async def test_publication_and_replay_treat_access_scope_as_immutable():
    draft_type, publisher = classes()
    draft = draft_type.from_environment(
        config(),
        **(inputs() | {"allowed_clients": frozenset(), "all_clients": True}),
    )
    repo, actor = Repository(), uuid4()
    service = publisher(repo, Transactions(), Clock())
    policy = await service.publish(draft, actor_id=actor)
    assert policy.all_clients and policy.allows_client(uuid4())
    assert draft.to_document()["all_clients"] is True
    assert await service.publish(draft, actor_id=actor) is policy
    changed = replace(
        draft, all_clients=False, allowed_clients=frozenset({uuid4()})
    )
    with pytest.raises(ValueError, match="policy_version_conflict"):
        await service.publish(changed, actor_id=actor)


def test_cli_public_scope_is_explicit_and_cannot_mix_allowlist(
    monkeypatch, capsys
):
    from tests.unit.test_financial_policy_config import arguments, module

    command = module()
    monkeypatch.setattr(
        command, "load_config", lambda: SimpleNamespace(financial=config())
    )
    old = arguments()
    public = old[:-2] + ["--all-clients"]
    assert command.main(public) == 0
    document = json.loads(capsys.readouterr().out)
    assert document["all_clients"] is True and document["allowed_clients"] == []
    with pytest.raises(SystemExit):
        command.main(old + ["--all-clients"])
    with pytest.raises(SystemExit):
        command.main(old[:-2])
