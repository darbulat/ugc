"""Caller-owned transaction boundaries for attach-only identity proof."""

from collections.abc import Callable
from datetime import datetime
from typing import Protocol
from uuid import UUID

from ugc_bot.domain.messenger_linking import (
    LinkContext,
    LinkReadState,
    LinkReceipt,
    LinkScope,
    MaxLinkActor,
    NativeLinkProposal,
)


class LinkTokenCodec(Protocol):
    scope: LinkScope

    def derive(self, context: LinkContext) -> str: ...
    def verifier(self, token: str) -> str: ...
    def launch_url(self, context: LinkContext) -> str: ...


ContextFactory = Callable[[datetime], tuple[LinkContext, str]]
ClockReader = Callable[[], datetime]
ContextVerifier = Callable[[LinkContext], str | None]


class MessengerLinkingRepository(Protocol):
    async def create(
        self,
        actor: MaxLinkActor,
        operation_key: str,
        context_factory: ContextFactory | None,
        *,
        allow_new: bool,
        scope: LinkScope | None,
        clock: ClockReader,
        session: object,
    ) -> LinkReceipt: ...
    async def read(
        self,
        actor: MaxLinkActor,
        challenge_id: UUID | None,
        *,
        clock: ClockReader,
        session: object,
    ) -> LinkReadState: ...
    async def confirm(
        self,
        actor: MaxLinkActor,
        challenge_id: UUID,
        claim_id: UUID,
        expected_version: int,
        operation_key: str,
        *,
        allow_new: bool,
        proof_verifier: ContextVerifier,
        scope: LinkScope | None,
        clock: ClockReader,
        session: object,
    ) -> LinkReceipt: ...
    async def revoke(
        self,
        actor: MaxLinkActor,
        challenge_id: UUID,
        expected_version: int,
        operation_key: str,
        *,
        clock: ClockReader,
        session: object,
    ) -> LinkReceipt: ...
    async def record_native(
        self, native: NativeLinkProposal, *, clock: ClockReader, session: object
    ) -> LinkReceipt | None: ...
    async def propose(
        self,
        native: NativeLinkProposal,
        *,
        allow_new: bool,
        proof_verifier: ContextVerifier,
        scope: LinkScope | None,
        clock: ClockReader,
        session: object,
    ) -> LinkReceipt: ...
