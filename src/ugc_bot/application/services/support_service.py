"""Support service for helpdesk message forwarding."""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

from ugc_bot.application.ports import SupportMessageRepository
from ugc_bot.domain.entities import SupportMessage

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SupportService:
    """Support message forwarding between Max and TG."""

    support_message_repo: SupportMessageRepository
    transaction_manager: Any = None

    async def record_forwarded_message(
        self,
        user_chat_id: str,
        support_chat_message_id: int,
        user_text: str | None = None,
    ) -> SupportMessage:
        """Record a forwarded support message."""
        msg = SupportMessage(
            id=uuid4(),
            user_chat_id=user_chat_id,
            support_chat_message_id=support_chat_message_id,
            user_text=user_text,
            created_at=datetime.utcnow(),
        )
        await self.support_message_repo.save(msg)
        logger.info(
            "Support message recorded",
            extra={
                "event_type": "support_message_forwarded",
                "user_chat_id": user_chat_id,
                "support_chat_message_id": support_chat_message_id,
            },
        )
        return msg

    async def find_user_by_support_reply(
        self, support_chat_message_id: int
    ) -> Optional[str]:
        """Find the Max user chat_id for a support reply."""
        msg = await self.support_message_repo.get_by_support_message_id(
            support_chat_message_id
        )
        if msg is None:
            return None
        return msg.user_chat_id
