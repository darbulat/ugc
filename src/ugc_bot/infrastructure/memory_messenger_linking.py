"""Deterministic in-memory attach-only repository for isolated service tests."""

import hashlib
import json
from dataclasses import asdict, replace
from datetime import timedelta
from uuid import NAMESPACE_URL, uuid4, uuid5

from ugc_bot.domain.enums import UserStatus
from ugc_bot.domain.messenger_linking import (
    LinkReadState,
    LinkReceipt,
    MaxLinkActor,
)
from ugc_bot.infrastructure.messenger.link_tokens import token_verifier


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), default=str
        ).encode()
    ).hexdigest()


def native_key(native):
    return native.bot_id, native.update_id


def native_digest(native):
    return digest(asdict(native))


def native_receipt(native, state, challenge_id=None, version=0, claim_id=None):
    identifier = uuid5(
        NAMESPACE_URL,
        f"ugc:link-native:{native.bot_id}:{native.update_id}:{native_digest(native)}",
    )
    return LinkReceipt(
        identifier, "proposal", challenge_id, state, version, claim_id
    )


class MemoryMessengerLinkingRepository:
    def __init__(self, users=None, advertisers=None):
        self.users = users or {}
        self.advertisers = advertisers or set()
        self.challenges = {}
        self.states = {}
        self.transitions = {}
        self.claim_challenges = {}
        self.claims = {}
        self.commands = {}
        self.native_attempts = {}
        self.native_results = {}
        self.native_conflicts = set()
        self.active_owner = {}
        self.active_tg = {}

    def _state(self, cid):
        actual = self.states.get(cid)
        history = self.transitions.get(cid, [])
        if not history or actual != history[-1]:
            raise ValueError("messenger_state_unavailable")
        claim_id = actual[2]
        if claim_id and self.claim_challenges.get(claim_id) != cid:
            raise ValueError("messenger_state_unavailable")
        return actual

    def _set_state(self, cid, value, version, claim_id):
        state = value, version, claim_id
        self.states[cid] = state
        self.transitions.setdefault(cid, []).append(state)

    def _owner(self, actor):
        user = self.users.get(actor.user_id)
        if user is None or user.max_id != actor.external_id:
            raise PermissionError("messenger_identity_changed")
        return user

    def _eligible(self, user):
        return (
            user.status == UserStatus.ACTIVE
            and user.user_id in self.advertisers
        )

    def _challenge(self, actor, identifier):
        row = self.challenges.get(identifier)
        if (
            row is None
            or row[0].owner_id != actor.user_id
            or row[0].max_id != actor.external_id
        ):
            raise LookupError("messenger_link_not_found")
        return row[0]

    def _live_telegram(self, sender_id, now):
        live = []
        for claim_id, claim in self.claims.items():
            if claim.sender_id != sender_id:
                continue
            cid = self.claim_challenges[claim_id]
            ctx = self.challenges[cid][0]
            if not ctx.issued_at <= now < ctx.expires_at:
                continue
            state = self._state(cid)
            if state[0] == "proposed":
                if self.active_owner.get(ctx.owner_id) != cid:
                    raise ValueError("messenger_state_unavailable")
                live.append(cid)
        if len(live) > 1 or (live and self.active_tg.get(sender_id) != live[0]):
            raise ValueError("messenger_state_unavailable")
        return live[0] if live else None

    def _live_owner(self, actor, now):
        live = []
        for cid, (ctx, _) in self.challenges.items():
            if (
                ctx.owner_id != actor.user_id
                or ctx.max_id != actor.external_id
                or not ctx.issued_at <= now < ctx.expires_at
            ):
                continue
            state, _, claim_id = self._state(cid)
            if state in {"waiting", "proposed"}:
                live.append(cid)
                if claim_id:
                    self._live_telegram(self.claims[claim_id].sender_id, now)
        if len(live) > 1 or (
            live and self.active_owner.get(actor.user_id) != live[0]
        ):
            raise ValueError("messenger_state_unavailable")

    def _prior(self, actor, key, payload):
        if not key or len(key) > 256:
            raise ValueError("invalid_operation_key")
        record = self.commands.get((actor.user_id, key))
        if record:
            if record[0] != digest(payload):
                raise ValueError("idempotency_payload_conflict")
            return record[1]
        return None

    def _save(
        self, actor, key, payload, kind, cid, state, version=0, claim_id=None
    ):
        receipt = LinkReceipt(uuid4(), kind, cid, state, version, claim_id)
        self.commands[actor.user_id, key] = digest(payload), receipt
        return receipt

    async def read(self, actor, challenge_id, *, clock, session):
        now = clock()
        user = self._owner(actor)
        self._live_owner(actor, now)
        cid = challenge_id or self.active_owner.get(actor.user_id)
        if cid is None:
            return LinkReadState(
                None,
                "linked" if user.telegram_id else "not_requested",
                telegram_id=user.telegram_id,
                eligible=self._eligible(user),
            )
        ctx = self._challenge(actor, cid)
        projection = self._state(cid)
        state, version, claim_id = projection
        claim = self.claims.get(claim_id)
        if state == "linked":
            if claim is None or user.telegram_id != claim.sender_id:
                state = "identity_changed"
        elif user.telegram_id is not None:
            state = "identity_changed"
        elif now >= ctx.expires_at and state in {
            "waiting",
            "proposed",
            "conflict",
        }:
            state = "expired"
        elif now < ctx.issued_at:
            state = "unavailable"
        return LinkReadState(
            ctx,
            state,
            version,
            claim_id,
            claim.sender_id if claim else None,
            claim.display_name if claim else None,
            claim.username if claim else None,
            self._eligible(user),
            self.challenges[cid][1],
        )

    async def create(
        self,
        actor,
        operation_key,
        context_factory,
        *,
        allow_new,
        scope,
        clock,
        session,
    ):
        now = clock()
        user = self._owner(actor)
        payload = {"kind": "create"}
        prior = self._prior(actor, operation_key, payload)
        if prior:
            return prior
        current = await self.read(actor, None, clock=clock, session=session)
        if current.state == "linked":
            return self._save(
                actor, operation_key, payload, "create", None, "linked"
            )
        if (
            not allow_new
            or not self._eligible(user)
            or context_factory is None
            or current.state == "identity_changed"
        ):
            return self._save(
                actor, operation_key, payload, "create", None, "unavailable"
            )
        if current.state in {"waiting", "proposed"}:
            return self._save(
                actor,
                operation_key,
                payload,
                "create",
                current.context.challenge_id,
                current.state,
                current.version,
                current.claim_id,
            )
        count = sum(
            ctx.owner_id == actor.user_id
            and now - timedelta(hours=1) < ctx.issued_at <= now
            for ctx, _ in self.challenges.values()
        )
        if count >= 5:
            return self._save(
                actor, operation_key, payload, "create", None, "rate_limited"
            )
        context, verifier = context_factory(now)
        self.challenges[context.challenge_id] = context, verifier
        self._set_state(context.challenge_id, "waiting", 1, None)
        self.active_owner[actor.user_id] = context.challenge_id
        return self._save(
            actor,
            operation_key,
            payload,
            "create",
            context.challenge_id,
            "waiting",
            1,
        )

    async def confirm(
        self,
        actor,
        challenge_id,
        claim_id,
        expected_version,
        operation_key,
        *,
        allow_new,
        proof_verifier,
        scope,
        clock,
        session,
    ):
        now = clock()
        user = self._owner(actor)
        payload = {
            "kind": "confirm",
            "challenge_id": challenge_id,
            "claim_id": claim_id,
            "version": expected_version,
        }
        prior = self._prior(actor, operation_key, payload)
        if prior:
            return prior
        ctx = self._challenge(actor, challenge_id)
        self._live_owner(actor, now)
        state, version, actual_claim = self._state(challenge_id)
        if (
            not allow_new
            or not self._eligible(user)
            or ctx.scope != scope
            or proof_verifier(ctx) != self.challenges[challenge_id][1]
        ):
            return self._save(
                actor,
                operation_key,
                payload,
                "confirm",
                challenge_id,
                "unavailable",
                version,
                actual_claim,
            )
        if expected_version != version:
            raise ValueError("link_version_conflict")
        if (
            state != "proposed"
            or claim_id != actual_claim
            or not ctx.issued_at <= now < ctx.expires_at
        ):
            raise ValueError("link_not_confirmable")
        claim = self.claims[claim_id]
        if user.telegram_id is not None or any(
            other.telegram_id == claim.sender_id
            for other in self.users.values()
        ):
            self._set_state(challenge_id, "conflict", version + 1, claim_id)
            return self._save(
                actor,
                operation_key,
                payload,
                "confirm",
                challenge_id,
                "conflict",
                version + 1,
                claim_id,
            )
        self.users[actor.user_id] = replace(user, telegram_id=claim.sender_id)
        self._set_state(challenge_id, "linked", version + 1, claim_id)
        return self._save(
            actor,
            operation_key,
            payload,
            "confirm",
            challenge_id,
            "linked",
            version + 1,
            claim_id,
        )

    async def revoke(
        self,
        actor,
        challenge_id,
        expected_version,
        operation_key,
        *,
        clock,
        session,
    ):
        self._owner(actor)
        payload = {
            "kind": "revoke",
            "challenge_id": challenge_id,
            "version": expected_version,
        }
        prior = self._prior(actor, operation_key, payload)
        if prior:
            return prior
        self._challenge(actor, challenge_id)
        self._live_owner(actor, clock())
        state, version, claim_id = self._state(challenge_id)
        if expected_version != version:
            raise ValueError("link_version_conflict")
        if state not in {"waiting", "proposed", "conflict"}:
            raise ValueError("link_not_revocable")
        self._set_state(challenge_id, "revoked", version + 1, claim_id)
        return self._save(
            actor,
            operation_key,
            payload,
            "revoke",
            challenge_id,
            "revoked",
            version + 1,
            claim_id,
        )

    async def record_native(self, native, *, clock, session):
        now = clock()
        key, fingerprint = native_key(native), native_digest(native)
        prior = self.native_attempts.get(key)
        if prior:
            if prior[0] != fingerprint:
                self.native_conflicts.add((key, fingerprint))
                return native_receipt(native, "conflict")
            return self.native_results.get(key)
        count = sum(
            at[1] == native.sender_id
            and at[2] == native.bot_id
            and now - timedelta(minutes=10) < at[3] <= now
            for at in self.native_attempts.values()
        )
        self.native_attempts[key] = (
            fingerprint,
            native.sender_id,
            native.bot_id,
            now,
        )
        if count >= 20:
            receipt = native_receipt(native, "rate_limited")
            self.native_results[key] = receipt
            return receipt
        return None

    def _native_result(self, native, state, cid=None, version=0, claim_id=None):
        receipt = native_receipt(native, state, cid, version, claim_id)
        self.native_results[native_key(native)] = receipt
        return receipt

    def _reserved_elsewhere(self, sender_id, cid, now):
        reserved = self._live_telegram(sender_id, now)
        return reserved is not None and reserved != cid

    def _challenge_for_token(self, token):
        try:
            verifier = token_verifier(token)
        except ValueError:
            return None
        return next(
            (row for row in self.challenges.values() if row[1] == verifier),
            None,
        )

    async def propose(
        self, native, *, allow_new, proof_verifier, scope, clock, session
    ):
        now = clock()
        previous = self.native_results.get(native_key(native))
        if previous:
            return previous
        if not allow_new or scope is None or scope.bot_id != native.bot_id:
            return self._native_result(native, "unavailable")
        row = self._challenge_for_token(native.token)
        if row is None:
            return self._native_result(native, "invalid")
        ctx = row[0]
        user = self.users.get(ctx.owner_id)
        cid = ctx.challenge_id
        self._live_owner(
            MaxLinkActor(ctx.owner_id, ctx.max_id),
            now,
        )
        state, version, claim_id = self._state(cid)
        if (
            user is None
            or user.max_id != ctx.max_id
            or user.telegram_id is not None
            or not self._eligible(user)
            or ctx.scope != scope
            or proof_verifier(ctx) != row[1]
        ):
            return self._native_result(native, "unavailable")
        if not ctx.issued_at <= now < ctx.expires_at or state not in {
            "waiting",
            "proposed",
        }:
            return self._native_result(
                native, "expired" if now >= ctx.expires_at else "unavailable"
            )
        if any(
            other.telegram_id == native.sender_id
            for other in self.users.values()
        ):
            self._set_state(cid, "conflict", version + 1, claim_id)
            return self._native_result(
                native, "conflict", cid, version + 1, claim_id
            )
        if self._reserved_elsewhere(native.sender_id, cid, now):
            return self._native_result(
                native, "conflict", cid, version, claim_id
            )
        if claim_id:
            if self.claims[claim_id].sender_id != native.sender_id:
                return self._native_result(
                    native, "conflict", cid, version, claim_id
                )
            return self._native_result(
                native, "proposed", cid, version, claim_id
            )
        claim_id = uuid5(
            NAMESPACE_URL, f"ugc:link-claim:{native.bot_id}:{native.update_id}"
        )
        self.claims[claim_id] = native
        self.claim_challenges[claim_id] = cid
        self._set_state(cid, "proposed", version + 1, claim_id)
        self.active_tg[native.sender_id] = cid
        return self._native_result(
            native, "proposed", cid, version + 1, claim_id
        )
