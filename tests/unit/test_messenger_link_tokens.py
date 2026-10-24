"""Reconstructible linking tokens are scoped, opaque and never safe receipts."""

import base64
import importlib
import importlib.util
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from pydantic import SecretStr


def modules():
    name = "ugc_bot.infrastructure.messenger.link_tokens"
    assert importlib.util.find_spec(name) is not None, (
        "link token adapter missing"
    )
    return importlib.import_module(name), importlib.import_module(
        "ugc_bot.domain.messenger_linking"
    )


def context(domain):
    now = datetime(2026, 10, 24, tzinfo=timezone.utc)
    scope = domain.LinkScope(123, "synthetic_test_bot", "test-1", "a" * 64)
    return domain.LinkContext(
        UUID(int=1),
        UUID(int=2),
        "333",
        scope,
        now,
        now + timedelta(minutes=10),
        "ab" * 32,
    )


def test_reconstructible_token_has_native_payload_bound_and_no_clear_storage():
    module, domain = modules()
    ctx = context(domain)
    adapter = module.LinkTokens(
        SecretStr(base64.urlsafe_b64encode(b"x" * 32).decode().rstrip("=")),
        ctx.scope,
    )
    token = adapter.derive(ctx)
    assert len(token) == 47 and token.startswith("lk1_")
    assert adapter.derive(ctx) == token
    assert adapter.verifier(token) == module.token_verifier(token)
    assert len(adapter.verifier(token)) == 64
    assert (
        adapter.launch_url(ctx)
        == f"https://t.me/synthetic_test_bot?start={token}"
    )
    assert token not in repr(adapter) + repr(ctx) + str(asdict(ctx))
    assert adapter.matches(token, ctx)
    assert not adapter.matches("lk1_" + "A" * 43, ctx)


@pytest.mark.parametrize(
    "field,value",
    [
        ("owner_id", UUID(int=3)),
        ("max_id", "444"),
        ("salt", "cd" * 32),
        ("challenge_id", UUID(int=4)),
    ],
)
def test_every_frozen_owner_context_changes_the_token(field, value):
    module, domain = modules()
    ctx = context(domain)
    adapter = module.LinkTokens(
        SecretStr(base64.urlsafe_b64encode(b"x" * 32).decode().rstrip("=")),
        ctx.scope,
    )
    assert adapter.derive(replace(ctx, **{field: value})) != adapter.derive(ctx)


def test_different_time_and_secret_change_token():
    module, domain = modules()
    ctx = context(domain)
    adapter = module.LinkTokens(
        SecretStr(base64.urlsafe_b64encode(b"x" * 32).decode().rstrip("=")),
        ctx.scope,
    )
    changed = replace(ctx, expires_at=ctx.expires_at + timedelta(seconds=1))
    assert adapter.derive(ctx) != adapter.derive(changed)
    assert adapter.derive(ctx) != module.LinkTokens(
        SecretStr(base64.urlsafe_b64encode(b"y" * 32).decode().rstrip("=")),
        ctx.scope,
    ).derive(ctx)


@pytest.mark.parametrize(
    "change",
    [
        {"bot_id": 124},
        {"bot_username": "another_test_bot"},
        {"key_id": "rotated"},
        {"max_bot_fingerprint": "b" * 64},
    ],
)
def test_changed_scope_never_derives_old_context(change):
    module, domain = modules()
    ctx = context(domain)
    adapter = module.LinkTokens(
        SecretStr(base64.urlsafe_b64encode(b"x" * 32).decode().rstrip("=")),
        replace(ctx.scope, **change),
    )
    with pytest.raises(ValueError, match="link_scope_unavailable"):
        adapter.derive(ctx)


@pytest.mark.parametrize("secret", ["", "x" * 31, "x" * 32, "x" * 43, "+" * 44])
def test_small_key_refused_without_key_value_in_exception(secret):
    module, domain = modules()
    with pytest.raises(ValueError, match="link_key_unavailable") as failure:
        module.LinkTokens(SecretStr(secret), context(domain).scope)
    assert not secret or secret not in str(failure.value)


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "lk1_",
        "lk1_!",
        "lk1_" + "x" * 44,
        "https://t.me/a",
        "lk1_" + "x" * 43 + " extra",
    ],
)
def test_malformed_token_is_rejected_without_echoing_it(bad):
    module, _ = modules()
    with pytest.raises(ValueError, match="invalid_link_token") as failure:
        module.token_verifier(bad)
    assert not bad or bad not in str(failure.value)


def test_receipt_and_native_repr_cannot_expose_bearer():
    _, domain = modules()
    ctx = context(domain)
    receipt = domain.LinkReceipt(
        UUID(int=8), "create", ctx.challenge_id, "waiting", 1
    )
    assert set(asdict(receipt)) == {
        "command_id",
        "kind",
        "challenge_id",
        "state",
        "version",
        "claim_id",
    }
    native = domain.NativeLinkProposal(
        123, "555", "100", "50", ctx.issued_at, "lk1_" + "A" * 43, "Name", None
    )
    assert native.token not in repr(native)
    assert "token" not in repr(native)


@pytest.mark.parametrize(
    "change",
    [
        {"bot_id": 0},
        {"bot_username": "bad/path"},
        {"key_id": "bad key"},
        {"max_bot_fingerprint": ""},
    ],
)
def test_invalid_security_scope_is_never_a_fallback(change):
    module, domain = modules()
    scope = replace(context(domain).scope, **change)
    key = SecretStr(base64.urlsafe_b64encode(b"x" * 32).decode().rstrip("="))
    with pytest.raises(ValueError, match="link_scope_unavailable"):
        module.LinkTokens(key, scope)
