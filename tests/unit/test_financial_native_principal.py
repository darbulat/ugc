"""Financial requests keep current native authority at the existing barrier."""

from dataclasses import FrozenInstanceError, asdict, replace
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from tests.application.services.test_rate_override_commands import create, setup
from tests.e2e.miniapp_helpers import generate_init_data
from ugc_bot.application.payout_ports import RequestPayout, ReviewPayout
from ugc_bot.application.services.payout_service import PayoutService


def principal(uid, platform="telegram", external_id="123"):
    from ugc_bot.application.native_principal_ports import (
        AuthenticatedMessengerPrincipal,
    )

    return AuthenticatedMessengerPrincipal(uid, platform, external_id)


class PayoutFacts:
    """Synthetic repository exposes when protected facts would be accessed."""

    def __init__(self, actor, recipient=None):
        self.actor = actor
        self.recipient = recipient or actor
        self.facts = dict(
            user_id=actor,
            telegram_id="123",
            max_id="456",
            status="active",
            admin=True,
        )
        self.events = []
        self.on_lock = None
        self.old = {"payload_hash": "unused", "result": {"private": "receipt"}}

    async def lock_users(self, ids, *, session):
        self.events.append(("users", tuple(sorted(set(ids), key=str))))
        if self.on_lock:
            self.on_lock()

    async def user(self, uid, *, session):
        self.events.append("actor")
        return self.facts

    async def get(self, table, uid, *, session):
        self.events.append(table)
        return dict(request_id=uid, recipient_id=self.recipient)

    async def command(self, actor, key, *, session):
        self.events.append("receipt")
        return self.old


def payout(repo):
    return PayoutService(
        repo,
        None,
        None,
        SimpleNamespace(now=lambda: datetime.now(timezone.utc)),
        SimpleNamespace(core_enabled=True, payouts_enabled=True),
    )


READS = (
    "get_for_actor",
    "list_for_actor",
    "requirements_for_actor",
    "reveal_for_admin",
    "requirements_for_admin",
    "history_for_admin",
    "operation_for_actor",
    "requisites_for_actor",
)


async def read(service, name, actor, proof):
    kwargs = dict(session=object(), principal=proof)
    if name == "reveal_for_admin":
        kwargs.update(
            operation_key="synthetic:reveal", reason="Synthetic audit"
        )
    if name in ("get_for_actor", "reveal_for_admin", "history_for_admin"):
        return await getattr(service, name)(uuid4(), actor, **kwargs)
    if name == "operation_for_actor":
        return await service.operation_for_actor(
            actor, "synthetic:key", **kwargs
        )
    return await getattr(service, name)(actor, **kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize("name", READS)
@pytest.mark.parametrize("binding", [None, "changed"])
async def test_all_older_payout_reads_revalidate_before_private_facts(
    name, binding
):
    actor = uuid4()
    repo = PayoutFacts(actor)
    repo.on_lock = lambda: repo.facts.update(telegram_id=binding)
    with pytest.raises(ValueError, match="^financial_principal_changed$"):
        await read(payout(repo), name, actor, principal(actor))
    assert "receipt" not in repo.events
    assert all(
        e in ("actor", "requests") or isinstance(e, tuple) for e in repo.events
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "platform,external", [("telegram", "123"), ("max", "456")]
)
async def test_current_platform_replay_keeps_original_command_hash_and_receipt(
    platform, external
):
    from ugc_bot.application.collaboration_ports import canonical
    from ugc_bot.application.payout_contracts import command_payload
    from ugc_bot.application.payout_ports import payout_payload_hash

    actor = uuid4()
    repo = PayoutFacts(actor)
    cmd = RequestPayout(
        actor_id=actor,
        operation_key="old-key",
        requisites_id=uuid4(),
        amount_minor=100,
    )
    before = asdict(cmd)
    repo.old["payload_hash"] = payout_payload_hash(
        canonical(command_payload(cmd))
    )
    result = await payout(repo).execute(
        cmd, session=object(), principal=principal(actor, platform, external)
    )
    assert result == {"private": "receipt"}
    assert asdict(cmd) == before
    assert repo.events == [("users", (actor,)), "actor", "receipt"]
    assert await payout(repo).execute(cmd, session=object()) == result


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", ["native", "uuid", "missing"])
async def test_scoped_payout_denies_after_full_user_barrier_before_replay(
    changed,
):
    actor, recipient = UUID(int=2), UUID(int=1)
    repo = PayoutFacts(actor, recipient)
    if changed == "native":
        repo.on_lock = lambda: repo.facts.update(telegram_id="rebound")
    elif changed == "missing":
        repo.on_lock = lambda: repo.facts.update(telegram_id=None)
    proof = principal(uuid4() if changed == "uuid" else actor)
    cmd = ReviewPayout(
        actor_id=actor,
        operation_key="review",
        request_id=uuid4(),
        expected_version=1,
        action="review",
        reason="Synthetic",
    )
    with pytest.raises(ValueError, match="^financial_principal_changed$"):
        await payout(repo).execute(cmd, session=object(), principal=proof)
    assert repo.events == ["requests", ("users", (recipient, actor)), "actor"]


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["execute", "get", "list"])
@pytest.mark.parametrize("binding", [None, "changed"])
async def test_override_denies_current_binding_change_on_all_admin_paths(
    method, binding
):
    repo, service, _, admin, _, recipient = setup()
    repo.users[admin] = replace(repo.users[admin], telegram_id="123")
    async with repo.transaction() as session:
        cmd = create(admin, recipient)
        result = await service.execute(cmd, session=session)
        repo.users[admin] = replace(repo.users[admin], telegram_id=binding)
        with pytest.raises(ValueError, match="^financial_principal_changed$"):
            if method == "execute":
                await service.execute(
                    cmd, session=session, principal=principal(admin)
                )
            elif method == "get":
                await service.get_for_admin(
                    result.override.approval.override_id,
                    actor_id=admin,
                    session=session,
                    principal=principal(admin),
                )
            else:
                await service.list_for_admin(
                    recipient,
                    "client",
                    "approved:test",
                    actor_id=admin,
                    session=session,
                    principal=principal(admin),
                )
    assert len(repo.commands) == len(repo.events) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "platform,external", [("telegram", "123"), ("max", "456")]
)
async def test_override_current_platform_replay_preserves_original_hash(
    platform, external
):
    from ugc_bot.application.override_ports import command_hash

    repo, service, _, admin, _, recipient = setup()
    repo.users[admin] = replace(
        repo.users[admin], telegram_id="123", max_id="456"
    )
    cmd = create(admin, recipient)
    before = asdict(cmd)
    async with repo.transaction() as session:
        first = await service.execute(cmd, session=session)
        assert (
            await service.execute(
                cmd,
                session=session,
                principal=principal(admin, platform, external),
            )
            == first
        )
        assert (
            await service.get_for_admin(
                first.override.approval.override_id,
                actor_id=admin,
                session=session,
                principal=principal(admin, platform, external),
            )
            == first.override
        )
        assert await service.list_for_admin(
            recipient,
            "client",
            "approved:test",
            actor_id=admin,
            session=session,
            principal=principal(admin, platform, external),
        ) == (first.override,)
    assert asdict(cmd) == before
    assert repo.commands[cmd.operation_key].payload_hash == command_hash(cmd)


class Roles:
    def __init__(self, user):
        self.user = user
        self.calls = 0

    async def get_user(self, external_id, messenger_type):
        self.calls += 1
        return self.user

    def __getattr__(self, name):
        raise AssertionError("unexpected identity write " + name)


def request(roles, *, telegram="synthetic-tg", max_token="synthetic-max"):
    app = SimpleNamespace(
        state=SimpleNamespace(
            config=SimpleNamespace(
                bot=SimpleNamespace(bot_token=telegram),
                max_bot=SimpleNamespace(token=max_token),
            ),
            dispatcher={"user_role_service": roles},
        )
    )
    return Request({"type": "http", "app": app})


@pytest.mark.asyncio
@pytest.mark.parametrize("platform", ["telegram", "max"])
async def test_financial_resolver_is_existing_only_and_preserves_country(
    platform,
):
    from ugc_bot.miniapp.financial_principal import resolve_financial_principal

    uid = uuid4()
    user = SimpleNamespace(
        user_id=uid, telegram_id="123", max_id="123", country=None
    )
    roles = Roles(user)
    token = "synthetic-tg" if platform == "telegram" else "synthetic-max"
    proof = await resolve_financial_principal(
        request(roles),
        generate_init_data(token, 123, "Synthetic"),
        platform=platform,
    )
    assert proof == principal(uid, platform)
    assert user.country is None and roles.calls == 1
    with pytest.raises(FrozenInstanceError):
        proof.external_id = "changed"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "user",
    [
        None,
        SimpleNamespace(user_id=uuid4(), telegram_id="other", max_id="other"),
    ],
)
async def test_unknown_financial_caller_never_creates_account(user):
    from ugc_bot.miniapp.financial_principal import resolve_financial_principal

    roles = Roles(user)
    with pytest.raises(HTTPException) as error:
        await resolve_financial_principal(
            request(roles),
            generate_init_data("synthetic-tg", 123, "Synthetic"),
            platform="telegram",
        )
    assert error.value.status_code == 404
    assert error.value.detail == "existing_financial_account_required"
    assert roles.calls == 1


@pytest.mark.parametrize(
    "values",
    [
        (UUID(int=0), "telegram", "123"),
        ("uuid", "telegram", "123"),
        (uuid4(), "unknown", "123"),
        (uuid4(), "telegram", ""),
        (uuid4(), "telegram", None),
        (uuid4(), "telegram", "a" * 129),
    ],
)
def test_trusted_principal_rejects_invalid_identity(values):
    with pytest.raises(ValueError, match="^financial_principal_invalid$"):
        principal(*values)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status,admin,error",
    [
        ("blocked", True, "active_actor_required"),
        ("pause", True, "active_admin_required"),
        ("active", False, "active_admin_required"),
    ],
)
async def test_current_payout_proof_does_not_bypass_current_status_or_role(
    status, admin, error
):
    actor = uuid4()
    repo = PayoutFacts(actor)
    repo.facts.update(status=status, admin=admin)
    with pytest.raises(ValueError, match="^" + error + "$"):
        await read(
            payout(repo), "requirements_for_admin", actor, principal(actor)
        )
    assert "receipt" not in repo.events


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["execute", "reveal_for_admin"])
async def test_missing_request_still_checks_requester_mapping_before_response(
    method,
):
    actor = uuid4()
    repo = PayoutFacts(actor)
    repo.facts["telegram_id"] = None

    async def missing(*args, **kwargs):
        return None

    repo.get = missing
    with pytest.raises(ValueError, match="^financial_principal_changed$"):
        if method == "execute":
            await payout(repo).execute(
                ReviewPayout(
                    actor_id=actor,
                    operation_key="review",
                    request_id=uuid4(),
                    expected_version=1,
                    action="review",
                    reason="Synthetic",
                ),
                session=object(),
                principal=principal(actor),
            )
        else:
            await read(payout(repo), method, actor, principal(actor))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kind",
    [
        "signature",
        "stale",
        "duplicate",
        "telegram_unconfigured",
        "max_unconfigured",
        "roles_missing",
        "invalid_user",
    ],
)
async def test_financial_resolver_sanitizes_invalid_or_unavailable_sessions(
    kind,
):
    from tests.unit.test_miniapp_session_freshness import signed
    from ugc_bot.miniapp.financial_principal import resolve_financial_principal

    user = SimpleNamespace(
        user_id=UUID(int=0) if kind == "invalid_user" else uuid4(),
        telegram_id="123",
        max_id="123",
    )
    roles = Roles(user)
    raw = generate_init_data("synthetic-tg", 123, "Synthetic")
    req = request(roles)
    platform = "telegram"
    if kind == "signature":
        raw = raw.replace("hash=", "hash=bad")
    elif kind == "stale":
        raw = signed(bot_token="synthetic-tg")
    elif kind == "duplicate":
        raw += "&auth_date=123"
    elif kind == "telegram_unconfigured":
        req = request(roles, telegram="")
    elif kind == "max_unconfigured":
        req = request(roles, max_token="")
        platform = "max"
    elif kind == "roles_missing":
        req.app.state.dispatcher.clear()
    with pytest.raises(HTTPException) as error:
        await resolve_financial_principal(req, raw, platform=platform)
    assert (error.value.status_code, error.value.detail) == (
        (503, "financial_unavailable")
        if kind == "roles_missing"
        else (401, "financial_session_invalid")
    )
    assert roles.calls == (1 if kind == "invalid_user" else 0)


def test_economic_hashes_remain_the_original_literal_payloads():
    from hashlib import sha256

    from ugc_bot.application.collaboration_ports import canonical
    from ugc_bot.application.override_ports import command_hash
    from ugc_bot.application.payout_contracts import command_payload
    from ugc_bot.application.payout_ports import payout_payload_hash

    actor, recipient = UUID(int=1), UUID(int=2)
    cmd = RequestPayout(
        actor_id=actor,
        operation_key="old",
        requisites_id=recipient,
        amount_minor=100,
    )
    expected = (
        b'{"actor_id":"00000000-0000-0000-0000-000000000001",'
        b'"amount_minor":100,'
        b'"currency":"RUB",'
        b'"operation_key":"old",'
        b'"requisites_id":"00000000-0000-0000-0000-000000000002"}'
    )
    assert (
        payout_payload_hash(canonical(command_payload(cmd)))
        == sha256(expected).hexdigest()
    )
    rate = create(actor, recipient, operation_key="old")
    expected_rate = (
        b'{"action":"create",'
        b'"actor_id":"00000000-0000-0000-0000-000000000001",'
        b'"effective_from":"2026-10-24T00:00:00.000000+00:00",'
        b'"effective_until":"2026-11-22T00:00:00.000000+00:00",'
        b'"operation_key":"old",'
        b'"policy_version":"approved:test",'
        b'"rate_bps":2000,'
        b'"reason":"explicit individual agreement",'
        b'"recipient_id":"00000000-0000-0000-0000-000000000002",'
        b'"side":"client"}'
    )
    assert command_hash(rate) == sha256(expected_rate).hexdigest()


@pytest.mark.asyncio
async def test_recipient_funding_check_remains_independent_of_requester_proof():
    from unittest.mock import AsyncMock

    admin, recipient, requirement = uuid4(), uuid4(), uuid4()
    replay = SimpleNamespace(balances={"debt": 0})
    repo = SimpleNamespace(
        user=AsyncMock(
            side_effect=[
                dict(
                    user_id=admin,
                    telegram_id="123",
                    max_id=None,
                    status="active",
                    admin=True,
                ),
                dict(
                    user_id=recipient,
                    telegram_id="789",
                    max_id=None,
                    status="active",
                    admin=False,
                ),
            ]
        ),
        requirements_lock=AsyncMock(),
        latest_requirements=AsyncMock(
            return_value=dict(requirements_id=requirement, enabled=True)
        ),
        legacy_clear=AsyncMock(),
        reconcile_locked=AsyncMock(return_value=replay),
        require_history_authority=AsyncMock(),
        unmatched_bank=AsyncMock(return_value=False),
    )
    service = payout(repo)
    await service._actor(
        admin, admin=True, principal=principal(admin), session=object()
    )
    assert (
        await service._clear(
            recipient, [], requirements_id=requirement, session=object()
        )
        is replay
    )
