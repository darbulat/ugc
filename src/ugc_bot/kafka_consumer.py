"""Kafka consumer for order activation events."""

import asyncio
import json
import logging
from typing import Any
from uuid import UUID

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer  # type: ignore[import-untyped]

from ugc_bot.application.services.offer_dispatch_service import OfferDispatchService
from ugc_bot.bot.handlers.security_warnings import BLOGGER_OFFER_WARNING
from ugc_bot.config import AppConfig, load_config
from ugc_bot.container import Container
from ugc_bot.logging_setup import configure_logging
from ugc_bot.startup_logging import log_startup_info

logger = logging.getLogger(__name__)


def _parse_order_id(data: dict[str, Any]) -> UUID | None:
    """Extract order_id from order_activation payload or None."""
    if data.get("event") != "order_activated":
        return None
    raw = data.get("order_id")
    if not raw:
        return None
    try:
        return UUID(raw)
    except ValueError:
        return None


async def _send_offers(
    order_id: UUID,
    bot: Bot,
    offer_dispatch_service: OfferDispatchService,
    dlq_producer: AIOKafkaProducer | None,
    dlq_topic: str,
    retries: int,
    retry_delay_seconds: float,
) -> None:
    order = await offer_dispatch_service.order_repo.get_by_id(order_id)
    if order is None:
        logger.warning(
            "Order not found for activation event", extra={"order_id": order_id}
        )
        return
    advertiser = await offer_dispatch_service.user_repo.get_by_id(order.advertiser_id)
    if advertiser is None:
        logger.warning(
            "Advertiser not found for activation event", extra={"order_id": order_id}
        )
        return

    advertisers_status = advertiser.status.value.upper()
    bloggers = await offer_dispatch_service.dispatch(order_id)
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
                    await _publish_dlq(
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


async def _publish_dlq(
    producer: AIOKafkaProducer | None, topic: str, payload: dict[str, Any]
) -> None:
    """Publish a message to the DLQ topic (best-effort)."""
    if producer is None:
        return
    try:
        await producer.send_and_wait(topic, payload)
    except Exception:
        logger.exception("Failed to publish DLQ message")


def _create_kafka_clients(
    config: AppConfig,
) -> tuple[AIOKafkaProducer, AIOKafkaConsumer]:
    """Create Kafka DLQ producer and activation consumer."""
    dlq_producer = AIOKafkaProducer(
        bootstrap_servers=config.kafka.kafka_bootstrap_servers,
        value_serializer=lambda value: json.dumps(value).encode("utf-8"),
    )
    consumer = AIOKafkaConsumer(
        config.kafka.kafka_topic,
        bootstrap_servers=config.kafka.kafka_bootstrap_servers,
        group_id=config.kafka.kafka_group_id,
        value_deserializer=lambda value: json.loads(value.decode("utf-8")),
        auto_offset_reset="earliest",
        enable_auto_commit=True,
    )
    return dlq_producer, consumer


async def _consume_forever(
    *,
    consumer: AIOKafkaConsumer,
    dlq_producer: AIOKafkaProducer,
    bot: Bot,
    offer_dispatch_service: OfferDispatchService,
    config: AppConfig,
) -> None:
    """Start Kafka clients and process activation events forever."""
    producer_started = False
    consumer_started = False
    try:
        await dlq_producer.start()
        producer_started = True
        await consumer.start()
        consumer_started = True

        async for msg in consumer:
            val = getattr(msg, "value", None)
            if not isinstance(val, dict):
                continue
            order_id = _parse_order_id(val)
            if order_id is None:
                continue
            await _send_offers(
                order_id,
                bot,
                offer_dispatch_service,
                dlq_producer,
                config.kafka.kafka_dlq_topic,
                config.kafka.kafka_send_retries,
                config.kafka.kafka_send_retry_delay_seconds,
            )
    finally:
        try:
            if consumer_started:
                await consumer.stop()
        finally:
            if producer_started:
                await dlq_producer.stop()
            await bot.session.close()


async def run_consumer() -> None:
    """Run Kafka consumer in a single event loop, processing messages asynchronously."""

    config = load_config()
    configure_logging(
        config.log.log_level, json_format=config.log.log_format.lower() == "json"
    )
    log_startup_info(logger=logger, service_name="kafka-consumer", config=config)
    if not config.kafka.kafka_enabled:
        logger.info("Kafka consumer disabled by config")
        return
    if not config.db.database_url:
        logger.error("DATABASE_URL is required for Kafka consumer")
        return

    container = Container(config)
    offer_dispatch_service = container.build_offer_dispatch_service()

    dlq_producer, consumer = _create_kafka_clients(config)
    logger.info("Kafka consumer started", extra={"topic": config.kafka.kafka_topic})

    bot = Bot(token=config.bot.bot_token)
    await _consume_forever(
        consumer=consumer,
        dlq_producer=dlq_producer,
        bot=bot,
        offer_dispatch_service=offer_dispatch_service,
        config=config,
    )


def main() -> None:
    """Entry point."""
    asyncio.run(run_consumer())


if __name__ == "__main__":  # pragma: no cover
    main()
