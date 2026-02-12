"""Kafka consumer for order activation events."""

import asyncio
import json
import logging
from typing import Any
from uuid import UUID

from aiogram import Bot
from aiokafka import (  # type: ignore[import-untyped]
    AIOKafkaConsumer,
    AIOKafkaProducer,
    TopicPartition,
)
from aiokafka.errors import (  # type: ignore[import-untyped]
    KafkaConnectionError,
    NoBrokersAvailable,
)
from aiokafka.structs import OffsetAndMetadata  # type: ignore[import-untyped]

from ugc_bot.application.messenger.dto import Button, Keyboard, KeyboardKind
from ugc_bot.application.messenger.ports import MessengerClient
from ugc_bot.application.services.offer_dispatch_service import (
    OfferDispatchService,
)
from ugc_bot.config import AppConfig, load_config
from ugc_bot.container import Container
from ugc_bot.domain.entities import Order, User
from ugc_bot.exception_hooks import (
    install_asyncio_exception_handler,
    install_exception_hooks,
)
from ugc_bot.infrastructure.messenger.telegram.client import (
    TelegramMessengerClient,
    is_user_blocked_bot,
)
from ugc_bot.logging_setup import configure_logging
from ugc_bot.startup_logging import log_startup_info

logger = logging.getLogger(__name__)

_KAFKA_BOOTSTRAP_MAX_RETRIES = 10
_KAFKA_BOOTSTRAP_RETRY_DELAY_SECONDS = 2.0


async def _start_kafka_client_with_retry(
    start_fn: object,
    client_name: str,
) -> None:
    """Start Kafka client with retry on connection errors."""
    if not callable(start_fn):
        raise TypeError("start_fn must be callable")
    last_exc: Exception | None = None
    for attempt in range(1, _KAFKA_BOOTSTRAP_MAX_RETRIES + 1):
        try:
            result = start_fn()
            if asyncio.iscoroutine(result):
                await result
            logger.info(
                "%s started successfully",
                client_name,
                extra={"attempt": attempt},
            )
            return
        except (KafkaConnectionError, NoBrokersAvailable) as exc:
            last_exc = exc
            if attempt == _KAFKA_BOOTSTRAP_MAX_RETRIES:
                logger.error(
                    "%s failed after %d attempts",
                    client_name,
                    _KAFKA_BOOTSTRAP_MAX_RETRIES,
                    extra={"error": str(exc)},
                )
                raise
            wait_sec = _KAFKA_BOOTSTRAP_RETRY_DELAY_SECONDS * attempt
            logger.warning(
                "Kafka bootstrap failed for %s, retrying in %.1fs",
                client_name,
                wait_sec,
                extra={"attempt": attempt, "error": str(exc)},
            )
            await asyncio.sleep(wait_sec)
    if last_exc:
        raise last_exc


def _parse_order_id(data: dict[str, Any]) -> UUID | None:
    """Extract order_id from order_activation payload or None."""
    if data.get("event") != "order_activated":
        return None
    raw = data.get("order_id")
    if not raw:
        logger.debug(
            "order_activation event missing order_id", extra={"data": data}
        )
        return None
    try:
        return UUID(raw)
    except ValueError:
        logger.warning(
            "Invalid order_id in order_activation event",
            extra={"order_id_raw": raw, "error": "invalid UUID format"},
        )
        return None


async def _send_offer_to_blogger(
    blogger: User,
    order: Order,
    advertisers_status: str,
    messenger_client: MessengerClient,
    offer_dispatch_service: OfferDispatchService,
    retries: int,
    retry_delay_seconds: float,
    dlq_producer: AIOKafkaProducer | None,
    dlq_topic: str,
) -> None:
    """Send offer to one blogger with retries."""
    if blogger.user_id == order.advertiser_id:
        logger.debug(
            "Skipping blogger: is advertiser",
            extra={"order_id": order.order_id, "blogger_id": blogger.user_id},
        )
        return
    if not blogger.external_id.isdigit():
        logger.debug(
            "Skipping blogger: invalid external_id",
            extra={"order_id": order.order_id, "blogger_id": blogger.user_id},
        )
        return

    for attempt in range(1, retries + 1):
        try:
            offer_text = offer_dispatch_service.format_offer(
                order, advertisers_status
            )
            reply_markup = Keyboard(
                kind=KeyboardKind.INLINE,
                rows=[
                    [
                        Button(
                            text="Готов снять UGC",
                            callback_data=f"offer:{order.order_id}",
                        )
                    ],
                    [
                        Button(
                            text="Пропустить",
                            callback_data=f"offer_skip:{order.order_id}",
                        )
                    ],
                ],
            )
            if order.product_photo_file_id:
                await messenger_client.send_photo(
                    chat_id=blogger.external_id,
                    file_id=order.product_photo_file_id,
                    caption=offer_text,
                    keyboard=reply_markup,
                )
            else:
                await messenger_client.send_text(
                    chat_id=blogger.external_id,
                    text=offer_text,
                    keyboard=reply_markup,
                )
            await offer_dispatch_service.record_offer_sent(
                order.order_id, blogger.user_id
            )
            logger.info(
                "Offer sent to blogger",
                extra={
                    "order_id": order.order_id,
                    "blogger_id": blogger.user_id,
                    "attempt": attempt,
                },
            )
            return
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
            if is_user_blocked_bot(exc):
                return
            if attempt >= retries:
                logger.error(
                    "All retries failed for offer send, publishing to DLQ",
                    extra={
                        "order_id": order.order_id,
                        "blogger_id": blogger.user_id,
                        "retries": retries,
                    },
                )
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


async def _send_offers(
    order_id: UUID,
    messenger_client: MessengerClient,
    offer_dispatch_service: OfferDispatchService,
    dlq_producer: AIOKafkaProducer | None,
    dlq_topic: str,
    retries: int,
    retry_delay_seconds: float,
) -> None:
    order, advertiser = await offer_dispatch_service.get_order_and_advertiser(
        order_id
    )
    if order is None:
        logger.warning(
            "Order not found for activation event", extra={"order_id": order_id}
        )
        return
    if advertiser is None:
        logger.warning(
            "Advertiser not found for activation event",
            extra={"order_id": order_id},
        )
        return

    advertisers_status = advertiser.status.value.upper()
    bloggers = await offer_dispatch_service.dispatch(order_id)
    logger.info(
        "Processing order activation",
        extra={
            "order_id": order_id,
            "bloggers_count": len(bloggers) if bloggers else 0,
        },
    )
    if not bloggers:
        logger.info(
            "No verified bloggers for offer", extra={"order_id": order_id}
        )
        return

    for blogger in bloggers:
        await _send_offer_to_blogger(
            blogger,
            order,
            advertisers_status,
            messenger_client,
            offer_dispatch_service,
            retries,
            retry_delay_seconds,
            dlq_producer,
            dlq_topic,
        )


async def _commit_message_offset(consumer: AIOKafkaConsumer, msg: Any) -> None:
    """Commit the offset for this message so it is not redelivered."""
    topic = getattr(msg, "topic", None)
    partition = getattr(msg, "partition", None)
    offset = getattr(msg, "offset", None)
    if topic is None or partition is None or offset is None:
        return
    tp = TopicPartition(topic, partition)
    await consumer.commit({tp: OffsetAndMetadata(offset + 1, "")})


async def _publish_dlq(
    producer: AIOKafkaProducer | None, topic: str, payload: dict[str, Any]
) -> None:
    """Publish a message to the DLQ topic (best-effort)."""
    if producer is None:
        logger.debug("DLQ producer disabled, skipping publish")
        return
    try:
        await producer.send_and_wait(topic, payload)
        logger.info(
            "DLQ message published",
            extra={"topic": topic, "event": payload.get("event")},
        )
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
        enable_auto_commit=False,
    )
    return dlq_producer, consumer


async def _consume_forever(
    *,
    consumer: AIOKafkaConsumer,
    dlq_producer: AIOKafkaProducer,
    bot: Bot,
    messenger_client: MessengerClient,
    offer_dispatch_service: OfferDispatchService,
    config: AppConfig,
) -> None:
    """Start Kafka clients and process activation events forever."""
    producer_started = False
    consumer_started = False
    try:
        await _start_kafka_client_with_retry(
            dlq_producer.start, "Kafka DLQ producer"
        )
        producer_started = True
        await _start_kafka_client_with_retry(consumer.start, "Kafka consumer")
        consumer_started = True
        logger.info("Kafka consumer subscribed, waiting for messages")

        async for msg in consumer:
            try:
                val = getattr(msg, "value", None)
                if not isinstance(val, dict):  # pragma: no cover
                    logger.debug(
                        "Skipping non-dict message",
                        extra={"msg": str(msg)},
                    )
                    await _commit_message_offset(consumer, msg)
                    continue
                order_id = _parse_order_id(val)
                if order_id is None:  # pragma: no cover
                    await _commit_message_offset(consumer, msg)
                    continue
                logger.info(
                    "Received order_activation event",
                    extra={
                        "order_id": order_id,
                        "partition": getattr(msg, "partition", None),
                        "offset": getattr(msg, "offset", None),
                    },
                )
                await _send_offers(
                    order_id,
                    messenger_client,
                    offer_dispatch_service,
                    dlq_producer,
                    config.kafka.kafka_dlq_topic,
                    config.kafka.kafka_send_retries,
                    config.kafka.kafka_send_retry_delay_seconds,
                )
                await _commit_message_offset(consumer, msg)
            except Exception:
                logger.exception(
                    "Error processing Kafka message, offset not committed",
                    extra={
                        "partition": getattr(msg, "partition", None),
                        "offset": getattr(msg, "offset", None),
                    },
                )
    finally:
        logger.info("Stopping Kafka consumer")
        try:
            if consumer_started:
                await consumer.stop()
                logger.info("Kafka consumer stopped")
        finally:
            if producer_started:
                await dlq_producer.stop()
                logger.info("Kafka DLQ producer stopped")
            await bot.session.close()


async def run_consumer() -> None:
    """Run Kafka consumer in single event loop, process messages async."""
    config = load_config()
    configure_logging(
        config.log.log_level,
        json_format=config.log.log_format.lower() == "json",
    )
    install_exception_hooks("kafka-consumer")
    install_asyncio_exception_handler("kafka-consumer")
    log_startup_info(
        logger=logger, service_name="kafka-consumer", config=config
    )
    if not config.kafka.kafka_enabled:
        logger.info("Kafka consumer disabled by config")
        return
    if not config.db.database_url:
        logger.error("DATABASE_URL is required for Kafka consumer")
        return

    container = Container(config)
    offer_dispatch_service = container.build_offer_dispatch_service()

    dlq_producer, consumer = _create_kafka_clients(config)
    logger.info(
        "Kafka consumer started", extra={"topic": config.kafka.kafka_topic}
    )

    bot = Bot(token=config.bot.bot_token)
    messenger_client = TelegramMessengerClient(bot)
    await _consume_forever(
        consumer=consumer,
        dlq_producer=dlq_producer,
        bot=bot,
        messenger_client=messenger_client,
        offer_dispatch_service=offer_dispatch_service,
        config=config,
    )


def main() -> None:
    """Entry point."""
    asyncio.run(run_consumer())


if __name__ == "__main__":  # pragma: no cover
    main()
