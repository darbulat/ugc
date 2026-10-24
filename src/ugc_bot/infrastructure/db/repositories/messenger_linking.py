"""User→role→identity locks; narrow attachment shares the caller transaction."""

import json
from dataclasses import asdict
from datetime import datetime, timedelta
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import func, insert, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from ugc_bot.domain.enums import UserStatus
from ugc_bot.domain.messenger_linking import (
    LinkContext,
    LinkReadState,
    LinkReceipt,
    LinkScope,
    MaxLinkActor,
)
from ugc_bot.infrastructure.db.messenger_linking_models import (
    ACTIVE_OWNER,
    ACTIVE_TG,
    CHALLENGES,
    CLAIMS,
    COMMANDS,
    EVENTS,
    NATIVE_ATTEMPTS,
    NATIVE_RESULTS,
    STATE,
)
from ugc_bot.infrastructure.db.models import AdvertiserProfileModel, UserModel
from ugc_bot.infrastructure.db.repositories.financial_items import _session
from ugc_bot.infrastructure.memory_messenger_linking import (
    digest,
    native_digest,
    native_receipt,
)
from ugc_bot.infrastructure.messenger.link_tokens import token_verifier

IDENTITY_LOCK = (172902, 1)
NATIVE_COUNTER_LOCK = (172902, 2)


def canonical(value):
    return json.loads(json.dumps(value, default=str))


def context_from(row):
    data = row["context"]
    context = LinkContext(
        UUID(data["challenge_id"]),
        UUID(data["owner_id"]),
        data["max_id"],
        LinkScope(**data["scope"]),
        datetime.fromisoformat(data["issued_at"]),
        datetime.fromisoformat(data["expires_at"]),
        data["salt"],
    )
    if (
        context.challenge_id,
        context.owner_id,
        context.max_id,
        context.issued_at,
        context.expires_at,
    ) != (
        row["challenge_id"],
        row["owner_id"],
        row["max_id"],
        row["issued_at"],
        row["expires_at"],
    ):
        raise ValueError("messenger_context_corrupt")
    return context


def receipt_from(data):
    return LinkReceipt(
        UUID(data["command_id"]),
        data["kind"],
        UUID(data["challenge_id"]) if data["challenge_id"] else None,
        data["state"],
        data["version"],
        UUID(data["claim_id"]) if data["claim_id"] else None,
    )


def source_id(native):
    return uuid5(
        NAMESPACE_URL, f"ugc:link-source:{native.bot_id}:{native.update_id}"
    )


async def acquire_link_identity_barrier(session):
    await _session(session).execute(
        text("SELECT pg_advisory_xact_lock(:ns,:key)"),
        dict(ns=IDENTITY_LOCK[0], key=IDENTITY_LOCK[1]),
    )


class SqlMessengerLinkingRepository:
    async def _row(self, db, table, condition, *, lock=False):
        query = select(table).where(condition)
        if lock:
            query = query.with_for_update()
        return (await db.execute(query)).mappings().one_or_none()

    async def _owner(self, actor, db):
        user = await db.scalar(
            select(UserModel)
            .where(UserModel.user_id == actor.user_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if user is None or user.max_id != actor.external_id:
            raise PermissionError("messenger_identity_changed")
        profile = await db.scalar(
            select(AdvertiserProfileModel.user_id)
            .where(AdvertiserProfileModel.user_id == actor.user_id)
            .with_for_update(read=True, key_share=True)
        )
        await acquire_link_identity_barrier(db)
        return user, user.status == UserStatus.ACTIVE and profile is not None

    async def _challenge(self, actor, cid, db):
        row = await self._row(db, CHALLENGES, CHALLENGES.c.challenge_id == cid)
        if (
            row is None
            or row["owner_id"] != actor.user_id
            or row["max_id"] != actor.external_id
        ):
            raise LookupError("messenger_link_not_found")
        return row, context_from(row)

    async def _live_telegram(self, db, sender_id, now):
        rows = (
            (
                await db.execute(
                    select(CHALLENGES, CLAIMS.c.claim_id)
                    .join(
                        CLAIMS,
                        CLAIMS.c.challenge_id == CHALLENGES.c.challenge_id,
                    )
                    .where(
                        CLAIMS.c.telegram_id == sender_id,
                        CHALLENGES.c.issued_at <= now,
                        CHALLENGES.c.expires_at > now,
                    )
                )
            )
            .mappings()
            .all()
        )
        live = []
        for row in rows:
            ctx = context_from(row)
            state = await self._verified_state(db, ctx.challenge_id)
            if state["state"] == "proposed":
                owner = await self._row(
                    db, ACTIVE_OWNER, ACTIVE_OWNER.c.owner_id == ctx.owner_id
                )
                if owner is None or owner["challenge_id"] != ctx.challenge_id:
                    raise ValueError("messenger_state_unavailable")
                live.append(ctx.challenge_id)
        active = await self._row(
            db, ACTIVE_TG, ACTIVE_TG.c.telegram_id == sender_id
        )
        if len(live) > 1 or (
            live and (active is None or active["challenge_id"] != live[0])
        ):
            raise ValueError("messenger_state_unavailable")
        return live[0] if live else None

    async def _live_owner(self, actor, db, clock):
        now = clock()
        rows = (
            (
                await db.execute(
                    select(CHALLENGES).where(
                        CHALLENGES.c.owner_id == actor.user_id,
                        CHALLENGES.c.max_id == actor.external_id,
                        CHALLENGES.c.issued_at <= now,
                        CHALLENGES.c.expires_at > now,
                    )
                )
            )
            .mappings()
            .all()
        )
        live = []
        for row in rows:
            ctx = context_from(row)
            state = await self._verified_state(db, ctx.challenge_id)
            if state["state"] in {"waiting", "proposed"}:
                live.append(ctx.challenge_id)
                if state["claim_id"]:
                    claim = await self._row(
                        db, CLAIMS, CLAIMS.c.claim_id == state["claim_id"]
                    )
                    await self._live_telegram(db, claim["telegram_id"], now)
        active = await self._row(
            db, ACTIVE_OWNER, ACTIVE_OWNER.c.owner_id == actor.user_id
        )
        if len(live) > 1 or (
            live and (active is None or active["challenge_id"] != live[0])
        ):
            raise ValueError("messenger_state_unavailable")

    async def _current(self, actor, cid, user, eligible, db, clock):
        await self._live_owner(actor, db, clock)
        if cid is None:
            active = await self._row(
                db,
                ACTIVE_OWNER,
                ACTIVE_OWNER.c.owner_id == actor.user_id,
                lock=True,
            )
            cid = active["challenge_id"] if active else None
        if cid is None:
            return LinkReadState(
                None,
                "linked" if user.telegram_id else "not_requested",
                telegram_id=user.telegram_id,
                eligible=eligible,
            )
        row, ctx = await self._challenge(actor, cid, db)
        state = await self._verified_state(db, cid)
        claim = (
            await self._row(db, CLAIMS, CLAIMS.c.claim_id == state["claim_id"])
            if state["claim_id"]
            else None
        )
        now = clock()
        value = state["state"]
        if value == "linked":
            if claim is None or user.telegram_id != claim["telegram_id"]:
                value = "identity_changed"
        elif user.telegram_id is not None:
            value = "identity_changed"
        elif now >= ctx.expires_at and value in {
            "waiting",
            "proposed",
            "conflict",
        }:
            value = "expired"
        elif now < ctx.issued_at:
            value = "unavailable"
        identity = claim["identity"] if claim else {}
        return LinkReadState(
            ctx,
            value,
            state["version"],
            state["claim_id"],
            claim["telegram_id"] if claim else None,
            identity.get("display_name"),
            identity.get("username"),
            eligible,
            row["verifier"],
        )

    async def read(self, actor, challenge_id, *, clock, session):
        db = _session(session)
        user, eligible = await self._owner(actor, db)
        return await self._current(
            actor, challenge_id, user, eligible, db, clock
        )

    async def _prior(self, actor, key, payload, db):
        if not key or len(key) > 256:
            raise ValueError("invalid_operation_key")
        prior = await self._row(
            db,
            COMMANDS,
            (COMMANDS.c.owner_id == actor.user_id)
            & (COMMANDS.c.operation_key == key),
        )
        if prior:
            if prior["payload_hash"] != digest(payload):
                raise ValueError("idempotency_payload_conflict")
            return receipt_from(prior["receipt"])
        return None

    async def _event(self, db, kind, cid, fact, now):
        await db.execute(
            insert(EVENTS).values(
                event_id=uuid4(),
                challenge_id=cid,
                kind=kind,
                fact=canonical(fact),
                observed_at=now,
            )
        )

    async def _save(
        self, actor, key, payload, kind, cid, value, version, claim_id, db, now
    ):
        receipt = LinkReceipt(uuid4(), kind, cid, value, version, claim_id)
        await db.execute(
            insert(COMMANDS).values(
                command_id=receipt.command_id,
                owner_id=actor.user_id,
                operation_key=key,
                payload_hash=digest(payload),
                receipt=canonical(asdict(receipt)),
                recorded_at=now,
            )
        )
        await self._event(db, kind, cid, asdict(receipt), now)
        return receipt

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
        db = _session(session)
        user, eligible = await self._owner(actor, db)
        payload = {"kind": "create"}
        prior = await self._prior(actor, operation_key, payload, db)
        if prior:
            return prior
        current = await self._current(actor, None, user, eligible, db, clock)
        now = clock()
        if current.state == "linked":
            return await self._save(
                actor,
                operation_key,
                payload,
                "create",
                None,
                "linked",
                0,
                None,
                db,
                now,
            )
        if (
            not allow_new
            or not eligible
            or context_factory is None
            or current.state == "identity_changed"
        ):
            return await self._save(
                actor,
                operation_key,
                payload,
                "create",
                None,
                "unavailable",
                0,
                None,
                db,
                now,
            )
        if current.state in {"waiting", "proposed"}:
            return await self._save(
                actor,
                operation_key,
                payload,
                "create",
                current.context.challenge_id,
                current.state,
                current.version,
                current.claim_id,
                db,
                now,
            )
        count = await db.scalar(
            select(func.count())
            .select_from(CHALLENGES)
            .where(
                CHALLENGES.c.owner_id == actor.user_id,
                CHALLENGES.c.issued_at > now - timedelta(hours=1),
                CHALLENGES.c.issued_at <= now,
            )
        )
        if count >= 5:
            return await self._save(
                actor,
                operation_key,
                payload,
                "create",
                None,
                "rate_limited",
                0,
                None,
                db,
                now,
            )
        ctx, verifier = context_factory(now)
        await db.execute(
            insert(CHALLENGES).values(
                challenge_id=ctx.challenge_id,
                owner_id=actor.user_id,
                max_id=actor.external_id,
                context=canonical(asdict(ctx)),
                verifier=verifier,
                issued_at=now,
                expires_at=ctx.expires_at,
            )
        )
        await db.execute(
            insert(STATE).values(
                challenge_id=ctx.challenge_id,
                state="waiting",
                version=1,
                claim_id=None,
            )
        )
        await self._transition(db, ctx.challenge_id, "waiting", 1, None, now)
        await db.execute(
            pg_insert(ACTIVE_OWNER)
            .values(owner_id=actor.user_id, challenge_id=ctx.challenge_id)
            .on_conflict_do_update(
                index_elements=[ACTIVE_OWNER.c.owner_id],
                set_={"challenge_id": ctx.challenge_id},
            )
        )
        return await self._save(
            actor,
            operation_key,
            payload,
            "create",
            ctx.challenge_id,
            "waiting",
            1,
            None,
            db,
            now,
        )

    async def _verified_state(self, db, cid):
        state = await self._row(
            db, STATE, STATE.c.challenge_id == cid, lock=True
        )
        facts = list(
            (
                await db.scalars(
                    select(EVENTS.c.fact).where(
                        EVENTS.c.challenge_id == cid,
                        EVENTS.c.kind == "transition",
                    )
                )
            ).all()
        )
        if state is None or not facts:
            raise ValueError("messenger_state_unavailable")
        versions = [fact.get("version") for fact in facts]
        if any(type(v) is not int for v in versions) or sorted(
            versions
        ) != list(range(1, len(facts) + 1)):
            raise ValueError("messenger_state_unavailable")
        latest = max(facts, key=lambda fact: fact["version"])
        expected = canonical(
            {
                "challenge_id": cid,
                "state": state["state"],
                "version": state["version"],
                "claim_id": state["claim_id"],
            }
        )
        if latest != expected:
            raise ValueError("messenger_state_unavailable")
        if state["claim_id"]:
            claim = await self._row(
                db, CLAIMS, CLAIMS.c.claim_id == state["claim_id"]
            )
            if claim is None or claim["challenge_id"] != cid:
                raise ValueError("messenger_state_unavailable")
        return state

    async def _transition(self, db, cid, value, version, claim_id, now):
        await self._event(
            db,
            "transition",
            cid,
            {
                "challenge_id": cid,
                "state": value,
                "version": version,
                "claim_id": claim_id,
            },
            now,
        )

    async def _set_state(self, db, cid, value, version, claim_id, now):
        await db.execute(
            update(STATE)
            .where(STATE.c.challenge_id == cid)
            .values(state=value, version=version, claim_id=claim_id)
        )

        await self._transition(db, cid, value, version, claim_id, now)

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
        db = _session(session)
        user, eligible = await self._owner(actor, db)
        payload = {
            "kind": "confirm",
            "challenge_id": challenge_id,
            "claim_id": claim_id,
            "version": expected_version,
        }
        prior = await self._prior(actor, operation_key, payload, db)
        if prior:
            return prior
        row, ctx = await self._challenge(actor, challenge_id, db)
        await self._live_owner(actor, db, clock)
        state = await self._verified_state(db, challenge_id)
        now = clock()
        if (
            not allow_new
            or not eligible
            or ctx.scope != scope
            or proof_verifier(ctx) != row["verifier"]
        ):
            return await self._save(
                actor,
                operation_key,
                payload,
                "confirm",
                challenge_id,
                "unavailable",
                state["version"],
                state["claim_id"],
                db,
                now,
            )
        if expected_version != state["version"]:
            raise ValueError("link_version_conflict")
        if (
            state["state"] != "proposed"
            or claim_id != state["claim_id"]
            or not ctx.issued_at <= now < ctx.expires_at
        ):
            raise ValueError("link_not_confirmable")
        claim = await self._row(db, CLAIMS, CLAIMS.c.claim_id == claim_id)
        other = await db.scalar(
            select(UserModel.user_id).where(
                UserModel.telegram_id == claim["telegram_id"]
            )
        )
        attached = False
        if user.telegram_id is None and other is None:
            try:
                async with db.begin_nested():
                    result = await db.execute(
                        update(UserModel)
                        .where(
                            UserModel.user_id == actor.user_id,
                            UserModel.max_id == actor.external_id,
                            UserModel.telegram_id.is_(None),
                        )
                        .values(telegram_id=claim["telegram_id"])
                        .execution_options(synchronize_session=False)
                    )
                    attached = result.rowcount == 1
            except IntegrityError:
                attached = False
        now = clock()
        if attached and not ctx.issued_at <= now < ctx.expires_at:
            raise ValueError("link_not_confirmable")
        value = "linked" if attached else "conflict"
        version = state["version"] + 1
        await self._set_state(db, challenge_id, value, version, claim_id, now)
        return await self._save(
            actor,
            operation_key,
            payload,
            "confirm",
            challenge_id,
            value,
            version,
            claim_id,
            db,
            now,
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
        db = _session(session)
        await self._owner(actor, db)
        payload = {
            "kind": "revoke",
            "challenge_id": challenge_id,
            "version": expected_version,
        }
        prior = await self._prior(actor, operation_key, payload, db)
        if prior:
            return prior
        await self._challenge(actor, challenge_id, db)
        await self._live_owner(actor, db, clock)
        state = await self._verified_state(db, challenge_id)
        now = clock()
        if expected_version != state["version"]:
            raise ValueError("link_version_conflict")
        if state["state"] not in {"waiting", "proposed", "conflict"}:
            raise ValueError("link_not_revocable")
        await self._set_state(
            db,
            challenge_id,
            "revoked",
            state["version"] + 1,
            state["claim_id"],
            now,
        )
        return await self._save(
            actor,
            operation_key,
            payload,
            "revoke",
            challenge_id,
            "revoked",
            state["version"] + 1,
            state["claim_id"],
            db,
            now,
        )

    async def _native_result(
        self, db, native, value, now, cid=None, version=0, claim_id=None
    ):
        receipt = native_receipt(native, value, cid, version, claim_id)
        await db.execute(
            pg_insert(NATIVE_RESULTS)
            .values(
                result_id=receipt.command_id,
                source_id=source_id(native),
                payload_hash=native_digest(native),
                receipt=canonical(asdict(receipt)),
                observed_at=now,
            )
            .on_conflict_do_nothing(index_elements=[NATIVE_RESULTS.c.result_id])
        )
        return receipt

    async def _native_prior(self, db, native):
        row = await self._row(
            db,
            NATIVE_RESULTS,
            (NATIVE_RESULTS.c.source_id == source_id(native))
            & (NATIVE_RESULTS.c.payload_hash == native_digest(native)),
        )
        return receipt_from(row["receipt"]) if row else None

    async def record_native(self, native, *, clock, session):
        db = _session(session)
        await db.execute(
            text("SELECT pg_advisory_xact_lock(:ns,:key)"),
            dict(ns=NATIVE_COUNTER_LOCK[0], key=NATIVE_COUNTER_LOCK[1]),
        )
        now = clock()
        source = await self._row(
            db,
            NATIVE_ATTEMPTS,
            NATIVE_ATTEMPTS.c.source_id == source_id(native),
        )
        if source:
            if source["payload_hash"] != native_digest(native):
                return await self._native_result(db, native, "conflict", now)
            return await self._native_prior(db, native)
        count = await db.scalar(
            select(func.count())
            .select_from(NATIVE_ATTEMPTS)
            .where(
                NATIVE_ATTEMPTS.c.bot_id == native.bot_id,
                NATIVE_ATTEMPTS.c.sender_id == native.sender_id,
                NATIVE_ATTEMPTS.c.observed_at > now - timedelta(minutes=10),
                NATIVE_ATTEMPTS.c.observed_at <= now,
            )
        )
        await db.execute(
            insert(NATIVE_ATTEMPTS).values(
                source_id=source_id(native),
                bot_id=native.bot_id,
                sender_id=native.sender_id,
                update_id=native.update_id,
                payload_hash=native_digest(native),
                observed_at=now,
            )
        )
        if count >= 20:
            return await self._native_result(db, native, "rate_limited", now)
        return None

    async def _proposal_context(self, db, native):
        try:
            verifier = token_verifier(native.token)
        except ValueError:
            return None
        return await self._row(
            db, CHALLENGES, CHALLENGES.c.verifier == verifier
        )

    async def _claim_available(self, db, sender_id, cid, now):
        other = await db.scalar(
            select(UserModel.user_id).where(UserModel.telegram_id == sender_id)
        )
        if other is not None:
            return "canonical"
        active = await self._live_telegram(db, sender_id, now)
        if active is not None and active != cid:
            return "reserved"
        return None

    async def propose(
        self, native, *, allow_new, proof_verifier, scope, clock, session
    ):
        db = _session(session)
        row = await self._proposal_context(db, native)
        if row:
            ctx = context_from(row)
            try:
                user, eligible = await self._owner(
                    MaxLinkActor(ctx.owner_id, ctx.max_id), db
                )
            except PermissionError:
                await acquire_link_identity_barrier(db)
                return await self._native_result(
                    db, native, "unavailable", clock()
                )
        else:
            await acquire_link_identity_barrier(db)
        prior = await self._native_prior(db, native)
        if prior:
            return prior
        now = clock()
        if not allow_new or scope is None or scope.bot_id != native.bot_id:
            return await self._native_result(db, native, "unavailable", now)
        if row is None:
            return await self._native_result(db, native, "invalid", now)
        return await self._propose_current(
            db, native, row, ctx, user, eligible, scope, proof_verifier, clock
        )

    async def _propose_current(
        self, db, native, row, ctx, user, eligible, scope, proof_verifier, clock
    ):
        cid = ctx.challenge_id
        await self._live_owner(
            MaxLinkActor(ctx.owner_id, ctx.max_id), db, clock
        )
        state = await self._verified_state(db, cid)
        now = clock()
        if (
            not eligible
            or user.telegram_id is not None
            or ctx.scope != scope
            or proof_verifier(ctx) != row["verifier"]
        ):
            return await self._native_result(db, native, "unavailable", now)
        if not ctx.issued_at <= now < ctx.expires_at or state["state"] not in {
            "waiting",
            "proposed",
        }:
            return await self._native_result(
                db,
                native,
                "expired" if now >= ctx.expires_at else "unavailable",
                now,
            )
        conflict = await self._claim_available(db, native.sender_id, cid, now)
        if conflict:
            version = state["version"] + (1 if conflict == "canonical" else 0)
            if conflict == "canonical":
                await self._set_state(
                    db, cid, "conflict", version, state["claim_id"], now
                )
            return await self._native_result(
                db, native, "conflict", now, cid, version, state["claim_id"]
            )
        if state["claim_id"]:
            claim = await self._row(
                db, CLAIMS, CLAIMS.c.claim_id == state["claim_id"]
            )
            return await self._native_result(
                db,
                native,
                "proposed"
                if claim["telegram_id"] == native.sender_id
                else "conflict",
                now,
                cid,
                state["version"],
                state["claim_id"],
            )
        claim_id = uuid5(
            NAMESPACE_URL, f"ugc:link-claim:{native.bot_id}:{native.update_id}"
        )
        identity = {
            "bot_id": native.bot_id,
            "update_id": native.update_id,
            "message_id": native.message_id,
            "occurred_at": native.occurred_at,
            "display_name": native.display_name,
            "username": native.username,
        }
        await db.execute(
            insert(CLAIMS).values(
                claim_id=claim_id,
                challenge_id=cid,
                telegram_id=native.sender_id,
                identity=canonical(identity),
                observed_at=now,
            )
        )
        await db.execute(
            pg_insert(ACTIVE_TG)
            .values(telegram_id=native.sender_id, challenge_id=cid)
            .on_conflict_do_update(
                index_elements=[ACTIVE_TG.c.telegram_id],
                set_={"challenge_id": cid},
            )
        )
        await self._set_state(
            db, cid, "proposed", state["version"] + 1, claim_id, now
        )
        await self._event(
            db,
            "native_proposed",
            cid,
            {"claim_id": claim_id, "source_id": source_id(native)},
            now,
        )
        return await self._native_result(
            db, native, "proposed", now, cid, state["version"] + 1, claim_id
        )
