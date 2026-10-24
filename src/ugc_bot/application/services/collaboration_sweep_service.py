"""Versioned deadline processing; lifecycle state never authorizes money."""

import logging
from dataclasses import dataclass

from ugc_bot.application.collaboration_ports import CollaborationCommand
from ugc_bot.application.ports import TransactionManager
from ugc_bot.application.services.collaboration_service import (
    CollaborationService,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CollaborationSweepResult:
    attempted: int
    changed: int
    rejected: int


@dataclass(slots=True)
class CollaborationSweepService:
    lifecycle: CollaborationService
    transactions: TransactionManager

    async def run_once(self, *, limit: int = 100) -> CollaborationSweepResult:
        async with self.transactions.transaction() as session:
            candidates = await self.lifecycle.repository.list_due(
                self.lifecycle.clock.now(), limit, session=session
            )
        changed, rejected = 0, 0
        for candidate in candidates:
            command = CollaborationCommand(
                assignment_id=candidate.collaboration.assignment_id,
                action="advance",
                operation_key=f"scheduler:advance:{candidate.version}",
                expected_version=candidate.version,
                system_actor="collaboration_scheduler",
            )
            try:
                async with self.transactions.transaction() as session:
                    result = await self.lifecycle.execute(
                        command, session=session
                    )
            except ValueError as exc:
                # Another command may have changed the version after discovery.
                # The failed transaction leaves that newer state untouched.
                rejected += 1
                logger.warning(
                    "Collaboration deadline command rejected",
                    extra={
                        "assignment_id": str(command.assignment_id),
                        "reason": str(exc),
                    },
                )
                continue
            if result.collaboration.state != candidate.collaboration.state:
                changed += 1
        return CollaborationSweepResult(len(candidates), changed, rejected)
