"""Kafka consumer for order activation events."""

import asyncio
import json
import logging
from typing import Any
from uuid import UUID

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from kafka import KafkaConsumer, KafkaProducer  # type: ignore[import-untyped]

from ugc_bot.application.services.offer_dispatch_service import OfferDispatchService
from ugc_bot.bot.handlers.security_warnings import BLOGGER_OFFER_WARNING
from ugc_bot.config import load_config
from ugc_bot.infrastructure.db.repositories import (
    SqlAlchemyBloggerProfileRepository,
    SqlAlchemyOrderRepository,
    SqlAlchemyUserRepository,
)
from ugc_bot.infrastructure.db.session import create_session_factory
from ugc_bot.logging_setup import configure_logging

logger = logging.getLogger(__name__)


async def _send_offers(
    order_id: UUID,
    bot: Bot,
    offer_dispatch_service: OfferDispatchService,
    dlq_producer: KafkaProducer | None,
    dlq_topic: str,
    retries: int,
    retry_delay_seconds: float,
) -> None:
    order = offer_dispatch_service.order_repo.get_by_id(order_id)
    if order is None:
        logger.warning(
            "Order not found for activation event", extra={"order_id": order_id}
        )
        return
    advertiser = offer_dispatch_service.user_repo.get_by_id(order.advertiser_id)
    if advertiser is None:
        logger.warning(
            "Advertiser not found for activation event", extra={"order_id": order_id}
        )
        return

    advertisers_status = advertiser.status.value.upper()
    bloggers = offer_dispatch_service.dispatch(order_id)
    if not bloggers:
        logger.info("No verified bloggers for offer", extra={"order_id": order_id})
        return

    for blogger in bloggers:
        if not blogger.external_id.isdigit():
            continue
        # Skip sending order to its author
        if blogger.user_id == order.advertiser_id:
            continue
        for attempt in range(1, retries + 1):
            try:
                await bot.send_message(
                    chat_id=int(blogger.external_id),
                    text=offer_dispatch_service.format_offer(order, advertisers_status),
                    reply_markup=InlineKeyboardMarkup(
                        inline_keyboard=[
                            [
                                InlineKeyboardButton(
                                    text="Готов снять UGC",
                                    callback_data=f"offer:{order.order_id}",
                                )
                            ]
                        ]
                    ),
                )
                # Send security warning
                await bot.send_message(
                    chat_id=int(blogger.external_id),
                    text=BLOGGER_OFFER_WARNING,
                )
                break
            except Exception as exc:
                logger.warning(
                    "Failed to send offer message",
                    extra={
                        "order_id": order.order_id,
                        "blogger_id": blogger.user_id,
                        "attempt": attempt,
                        "error": str(exc),
                    },
                )
                if attempt >= retries:
                    _publish_dlq(
                        dlq_producer,
                        dlq_topic,
                        {
                            "event": "offer_send_failed",
                            "order_id": str(order.order_id),
                            "blogger_id": str(blogger.user_id),
                            "external_id": blogger.external_id,
                            "error": str(exc),
                        },
                    )
                else:
                    await asyncio.sleep(retry_delay_seconds)


def _handle_message(
    data: dict[str, Any],
    bot_token: str,
    offer_dispatch_service: OfferDispatchService,
    dlq_producer: KafkaProducer | None,
    dlq_topic: str,
    retries: int,
    retry_delay_seconds: float,
) -> None:
    if data.get("event") != "order_activated":
        return
    order_id_raw = data.get("order_id")
    if not order_id_raw:
        return
    try:
        order_id = UUID(order_id_raw)
    except ValueError:
        return

    async def _run() -> None:
        bot = Bot(token=bot_token)
        try:
            await _send_offers(
                order_id,
                bot,
                offer_dispatch_service,
                dlq_producer,
                dlq_topic,
                retries,
                retry_delay_seconds,
            )
        finally:
            await bot.session.close()

    asyncio.run(_run())


def main() -> None:
    """Run Kafka consumer loop."""

    config = load_config()
    configure_logging(config.log_level, json_format=config.log_format.lower() == "json")
    if not config.kafka_enabled:
        logger.info("Kafka consumer disabled by config")
        return
    session_factory = create_session_factory(config.database_url)
    user_repo = SqlAlchemyUserRepository(session_factory=session_factory)
    blogger_repo = SqlAlchemyBloggerProfileRepository(session_factory=session_factory)
    order_repo = SqlAlchemyOrderRepository(session_factory=session_factory)
    offer_dispatch_service = OfferDispatchService(
        user_repo=user_repo,
        blogger_repo=blogger_repo,
        order_repo=order_repo,
    )

    dlq_producer: KafkaProducer | None = KafkaProducer(
        bootstrap_servers=config.kafka_bootstrap_servers,
        value_serializer=lambda value: json.dumps(value).encode("utf-8"),
    )
    consumer = KafkaConsumer(
        config.kafka_topic,
        bootstrap_servers=config.kafka_bootstrap_servers,
        group_id=config.kafka_group_id,
        value_deserializer=lambda value: json.loads(value.decode("utf-8")),
        auto_offset_reset="earliest",
        enable_auto_commit=True,
    )
    logger.info("Kafka consumer started", extra={"topic": config.kafka_topic})
    for message in consumer:
        _handle_message(
            message.value,
            config.bot_token,
            offer_dispatch_service,
            dlq_producer,
            config.kafka_dlq_topic,
            config.kafka_send_retries,
            config.kafka_send_retry_delay_seconds,
        )


def _publish_dlq(
    producer: KafkaProducer | None, topic: str, payload: dict[str, Any]
) -> None:
    if producer is None:
        return
    try:
        producer.send(topic, payload)
        producer.flush()
    except Exception:
        logger.exception("Failed to publish DLQ message")


if __name__ == "__main__":  # pragma: no cover
    main()
