"""Safe receipts survive unknown replies; live URL authority is fresh."""

import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Protocol
from uuid import UUID, uuid4

from ugc_bot.application.messenger_linking_ports import (
    LinkTokenCodec,
    MessengerLinkingRepository,
)
from ugc_bot.application.ports import TransactionManager
from ugc_bot.domain.messenger_linking import (
    LinkContext,
    LinkReceipt,
    LinkView,
    MaxLinkActor,
    NativeLinkProposal,
)


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(timezone.utc)


@dataclass
class MessengerLinkingService:
    repository: MessengerLinkingRepository
    transactions: TransactionManager
    tokens: LinkTokenCodec | None
    enabled: bool = False
    clock: Clock = field(default_factory=SystemClock)

    @property
    def scope(self):
        return self.tokens.scope if self.tokens else None

    def _current_verifier(self, context: LinkContext) -> str | None:
        if self.tokens is None or context.scope != self.tokens.scope:
            return None
        return self.tokens.verifier(self.tokens.derive(context))

    async def _view(self, actor, challenge_id, session, receipt=None):
        state = await self.repository.read(
            actor, challenge_id, clock=self.clock.now, session=session
        )
        now = self.clock.now()
        context = state.context
        ready = self.enabled and self.tokens is not None and state.eligible
        live = (
            context is not None
            and context.issued_at <= now < context.expires_at
            and state.state in {"waiting", "proposed"}
        )
        compatible = (
            context is not None
            and context.scope == self.scope
            and state.verifier == self._current_verifier(context)
        )
        value = state.state
        if value in {"waiting", "proposed"} and (not ready or not compatible):
            value = "unavailable"
        identity = None
        if state.telegram_id:
            identity = {
                "id": state.telegram_id,
                "display_name": state.display_name,
                "username": state.username,
            }
        url = (
            self.tokens.launch_url(context)
            if ready and live and compatible
            else None
        )
        if receipt and receipt.state in {"rate_limited", "unavailable"}:
            value = receipt.state
        return LinkView(
            value,
            context.challenge_id if context else None,
            state.version,
            state.claim_id,
            context.expires_at if context else None,
            identity,
            bool(ready),
            bool(
                ready
                and value
                in {
                    "not_requested",
                    "expired",
                    "revoked",
                    "conflict",
                    "rate_limited",
                }
            ),
            bool(ready and live and compatible and value == "proposed"),
            bool(
                context and state.state in {"waiting", "proposed", "conflict"}
            ),
            url,
            receipt,
        )

    async def status(
        self, actor: MaxLinkActor, challenge_id: UUID | None = None
    ) -> LinkView:
        async with self.transactions.transaction() as session:
            return await self._view(actor, challenge_id, session)

    async def create(self, actor: MaxLinkActor, operation_key: str) -> LinkView:
        scope, tokens = self.scope, self.tokens

        def context_factory(now):
            context = LinkContext(
                uuid4(),
                actor.user_id,
                actor.external_id,
                scope,
                now,
                now + timedelta(seconds=600),
                secrets.token_hex(32),
            )
            return context, tokens.verifier(tokens.derive(context))

        async with self.transactions.transaction() as session:
            receipt = await self.repository.create(
                actor,
                operation_key,
                context_factory if scope and tokens else None,
                allow_new=self.enabled and self.tokens is not None,
                scope=self.scope,
                clock=self.clock.now,
                session=session,
            )
            return await self._view(
                actor, receipt.challenge_id, session, receipt
            )

    async def confirm(
        self,
        actor: MaxLinkActor,
        challenge_id: UUID,
        claim_id: UUID,
        expected_version: int,
        operation_key: str,
    ) -> LinkView:
        async with self.transactions.transaction() as session:
            receipt = await self.repository.confirm(
                actor,
                challenge_id,
                claim_id,
                expected_version,
                operation_key,
                allow_new=self.enabled and self.tokens is not None,
                proof_verifier=self._current_verifier,
                scope=self.scope,
                clock=self.clock.now,
                session=session,
            )
            return await self._view(
                actor, receipt.challenge_id, session, receipt
            )

    async def revoke(
        self,
        actor: MaxLinkActor,
        challenge_id: UUID,
        expected_version: int,
        operation_key: str,
    ) -> LinkView:
        async with self.transactions.transaction() as session:
            receipt = await self.repository.revoke(
                actor,
                challenge_id,
                expected_version,
                operation_key,
                clock=self.clock.now,
                session=session,
            )
            return await self._view(
                actor, receipt.challenge_id, session, receipt
            )

    async def propose_native(self, native: NativeLinkProposal) -> LinkReceipt:
        # Operational counter commits before User/business locks; no User FK.
        async with self.transactions.transaction() as session:
            previous = await self.repository.record_native(
                native, clock=self.clock.now, session=session
            )
        if previous is not None:
            return previous
        async with self.transactions.transaction() as session:
            return await self.repository.propose(
                native,
                allow_new=self.enabled and self.tokens is not None,
                proof_verifier=self._current_verifier,
                scope=self.scope,
                clock=self.clock.now,
                session=session,
            )
