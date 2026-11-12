"""Kafka consumer for order activation events."""

import asyncio
import json
import logging
from typing import Any
from uuid import UUID

import aiohttp
from aiogram import Bot
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramRetryAfter,
)
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
from ugc_bot.application.services.bot_texts_service import BotTextsService
from ugc_bot.application.services.offer_dispatch_service import (
    OfferDispatchService,
)
from ugc_bot.application.services.user_role_service import UserRoleService
from ugc_bot.config import AppConfig, load_config
from ugc_bot.container import Container
from ugc_bot.domain.entities import Order, User
from ugc_bot.domain.enums import OrderStatus, UserStatus
from ugc_bot.exception_hooks import (
    install_asyncio_exception_handler,
    install_exception_hooks,
)
from ugc_bot.infrastructure.messenger.max.client import (
    MaxAPIError,
    MaxMessengerClient,
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


def _offer_message_parts(text: str, *, photo: bool) -> list[str]:
    """Lossless plain-text chunks within both messengers' Unicode limits.

    Telegram captions allow 1024 UTF-16 units; MAX text allows 4000
    characters. Conservatively cap all subsequent chunks at 4000 UTF-16
    units, preserving Unicode code points and every original character.
    """
    parts: list[str] = []
    current: list[str] = []
    size = 0
    limit = 1024 if photo else 4000
    for char in text:
        units = 2 if ord(char) > 0xFFFF else 1
        if size + units > limit:
            parts.append("".join(current))
            current = []
            size = 0
            limit = 4000
        current.append(char)
        size += units
    parts.append("".join(current))
    return parts


def _definitely_rejected(exc: Exception) -> bool:
    return isinstance(
        exc, (TelegramBadRequest, TelegramForbiddenError, TelegramRetryAfter)
    ) or (isinstance(exc, MaxAPIError) and exc.status in {400, 403, 404, 429})


async def _send_offer_via_client(
    chat_id: str,
    messenger_client: MessengerClient,
    offer_text: str,
    reply_markup: Keyboard,
    order: Order,
    blogger: User,
    retries: int,
    retry_delay_seconds: float,
    offer_dispatch_service: OfferDispatchService,
    dlq_producer: AIOKafkaProducer | None,
    dlq_topic: str,
    messenger_label: str,
    user_role_service: UserRoleService | None = None,
    *,
    guarded: bool = False,
) -> bool | None:
    """Send offer to one chat_id via one messenger client with retries.

    Returns True if the message was delivered, False otherwise.
    """
    parts = _offer_message_parts(
        offer_text, photo=bool(order.product_photo_file_id)
    )
    delivered_parts = 0
    for attempt in range(1, (1 if guarded else retries) + 1):
        try:
            while delivered_parts < len(parts):
                part = parts[delivered_parts]
                keyboard = (
                    reply_markup if delivered_parts == len(parts) - 1 else None
                )
                if delivered_parts == 0 and order.product_photo_file_id:
                    await messenger_client.send_photo(
                        chat_id=chat_id,
                        file_id=order.product_photo_file_id,
                        caption=part,
                        keyboard=keyboard,
                    )
                else:
                    await messenger_client.send_text(
                        chat_id=chat_id,
                        text=part,
                        keyboard=keyboard,
                    )
                # A later failure resumes after already accepted parts.
                delivered_parts += 1
            logger.info(
                "Offer sent to blogger",
                extra={
                    "order_id": order.order_id,
                    "blogger_id": blogger.user_id,
                    "messenger": messenger_label,
                    "attempt": attempt,
                },
            )
            return True
        except Exception as exc:
            logger.warning(
                "Failed to send offer message",
                extra={
                    "order_id": order.order_id,
                    "blogger_id": blogger.user_id,
                    "messenger": messenger_label,
                    "attempt": attempt,
                    "error": type(exc).__name__ if guarded else str(exc),
                },
            )
            if guarded:
                return (
                    False
                    if delivered_parts == 0 and _definitely_rejected(exc)
                    else None
                )
            if is_user_blocked_bot(exc):
                if user_role_service is not None:
                    try:
                        await user_role_service.update_status(
                            blogger.user_id, UserStatus.BOT_BLOCKED
                        )
                    except Exception:
                        logger.exception(
                            "Failed to mark user as bot_blocked",
                            extra={"blogger_id": str(blogger.user_id)},
                        )
                return False
            if attempt >= retries:
                logger.error(
                    "All retries failed for offer send, publishing to DLQ",
                    extra={
                        "order_id": order.order_id,
                        "blogger_id": blogger.user_id,
                        "messenger": messenger_label,
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
                        "chat_id": chat_id,
                        "messenger": messenger_label,
                        "error": str(exc),
                    },
                )
            else:
                await asyncio.sleep(retry_delay_seconds)
    return False


async def _send_offer_to_blogger(
    blogger: User,
    order: Order,
    advertisers_status: str,
    messenger_clients: dict[str, MessengerClient],
    offer_dispatch_service: OfferDispatchService,
    retries: int,
    retry_delay_seconds: float,
    dlq_producer: AIOKafkaProducer | None,
    dlq_topic: str,
    locale: str = "ru",
    bot_texts_service: BotTextsService | None = None,
    user_role_service: UserRoleService | None = None,
    *,
    guarded: bool = False,
) -> bool | None:
    """Send offer to one blogger via all available messengers."""
    if blogger.user_id == order.advertiser_id:
        logger.debug(
            "Skipping blogger: is advertiser",
            extra={"order_id": order.order_id, "blogger_id": blogger.user_id},
        )
        return False if guarded else None

    # Build list of (chat_id, client, label) for all available messengers
    targets: list[tuple[str, MessengerClient, str]] = []
    if blogger.telegram_id and "telegram" in messenger_clients:
        targets.append(
            (blogger.telegram_id, messenger_clients["telegram"], "telegram")
        )
    if blogger.max_chat_id and "max" in messenger_clients:
        targets.append((blogger.max_chat_id, messenger_clients["max"], "max"))

    if not targets:
        logger.debug(
            "Skipping blogger: no valid messenger IDs",
            extra={"order_id": order.order_id, "blogger_id": blogger.user_id},
        )
        return False if guarded else None

    offer_text = await offer_dispatch_service.format_offer(
        order,
        advertisers_status,
        locale=locale,
        bot_texts_service=bot_texts_service,
    )
    btn_accept = "Готов снять UGC"
    btn_skip = "Пропустить"
    if bot_texts_service is not None:
        txts = await bot_texts_service.get_many(
            ["btn_offer_accept", "btn_offer_skip"], locale
        )
        btn_accept = txts.get("btn_offer_accept") or btn_accept
        btn_skip = txts.get("btn_offer_skip") or btn_skip
    reply_markup = Keyboard(
        kind=KeyboardKind.INLINE,
        rows=[
            [
                Button(
                    text=btn_accept,
                    callback_data=f"offer:{order.order_id}",
                )
            ],
            [
                Button(
                    text=btn_skip,
                    callback_data=f"offer_skip:{order.order_id}",
                )
            ],
        ],
    )

    any_sent = False
    for chat_id, client, label in targets:
        sent = await _send_offer_via_client(
            chat_id,
            client,
            offer_text,
            reply_markup,
            order,
            blogger,
            retries,
            retry_delay_seconds,
            offer_dispatch_service,
            dlq_producer,
            dlq_topic,
            label,
            user_role_service=user_role_service,
            guarded=guarded,
        )
        if guarded and sent is None:
            return None
        any_sent = any_sent or bool(sent)
        if guarded and sent:
            break

    if any_sent:
        await offer_dispatch_service.record_offer_sent(
            order.order_id, blogger.user_id
        )
    return any_sent if guarded else None


async def _claim_offer(service, order_id, blogger, run):
    if run is None:
        return (
            "stop" if await service.is_dispatch_stopped(order_id) else "claimed"
        )
    return await service.claim_dispatch_recipient(
        order_id, blogger.user_id, run
    )


async def _send_offers(
    order_id: UUID,
    messenger_clients: dict[str, MessengerClient],
    offer_dispatch_service: OfferDispatchService,
    dlq_producer: AIOKafkaProducer | None,
    dlq_topic: str,
    retries: int,
    retry_delay_seconds: float,
    bot_texts_service: BotTextsService | None = None,
    default_locale: str = "ru",
    user_role_service: UserRoleService | None = None,
    *,
    dispatch_run: int | None = None,
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

    if order.dispatch_stopped or (
        dispatch_run is not None and order.status != OrderStatus.ACTIVE
    ):
        return
    advertisers_status = advertiser.status.value.upper()
    bloggers = await offer_dispatch_service.dispatch(order_id)
    if dispatch_run is not None:
        bloggers = await offer_dispatch_service.prepare_dispatch_audience(
            order_id, bloggers, dispatch_run
        )
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
        claim = await _claim_offer(
            offer_dispatch_service, order_id, blogger, dispatch_run
        )
        if claim == "stop":
            break
        if claim == "skip":
            continue
        locale = blogger.language if blogger.language else default_locale
        result = await _send_offer_to_blogger(
            blogger,
            order,
            advertisers_status,
            messenger_clients,
            offer_dispatch_service,
            retries,
            retry_delay_seconds,
            dlq_producer,
            dlq_topic,
            locale=locale,
            bot_texts_service=bot_texts_service,
            user_role_service=user_role_service,
            guarded=dispatch_run is not None,
        )
        if dispatch_run is not None and result is False:
            await offer_dispatch_service.reject_dispatch_recipient(
                order_id, blogger.user_id, dispatch_run
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
        retry_backoff_ms=config.kafka.kafka_producer_retry_backoff_ms,
    )
    consumer = AIOKafkaConsumer(
        config.kafka.kafka_topic,
        bootstrap_servers=config.kafka.kafka_bootstrap_servers,
        group_id=config.kafka.kafka_group_id,
        value_deserializer=lambda value: json.loads(value.decode("utf-8")),
        auto_offset_reset="earliest",
        enable_auto_commit=False,
        heartbeat_interval_ms=config.kafka.kafka_consumer_heartbeat_interval_ms,
        session_timeout_ms=config.kafka.kafka_consumer_session_timeout_ms,
    )
    return dlq_producer, consumer


async def _consume_forever(
    *,
    consumer: AIOKafkaConsumer,
    dlq_producer: AIOKafkaProducer,
    bot: Bot,
    messenger_clients: dict[str, MessengerClient],
    offer_dispatch_service: OfferDispatchService,
    config: AppConfig,
    bot_texts_service: BotTextsService | None = None,
    default_locale: str = "ru",
    user_role_service: UserRoleService | None = None,
    tracked_clients: dict[str, MessengerClient] | None = None,
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
                dispatch_run = val.get("dispatch_run")
                if (
                    dispatch_run is None
                    and await offer_dispatch_service.has_tracked_dispatch(
                        order_id
                    )
                ):
                    await _commit_message_offset(consumer, msg)
                    continue
                clients = messenger_clients
                if dispatch_run is not None:
                    if (
                        type(dispatch_run) is not int
                        or dispatch_run < 1
                        or not tracked_clients
                    ):
                        raise ValueError("invalid_tracked_dispatch")
                    clients = tracked_clients
                await _send_offers(
                    order_id,
                    clients,
                    offer_dispatch_service,
                    dlq_producer,
                    config.kafka.kafka_dlq_topic,
                    config.kafka.kafka_send_retries,
                    config.kafka.kafka_send_retry_delay_seconds,
                    bot_texts_service=bot_texts_service,
                    default_locale=default_locale,
                    user_role_service=user_role_service,
                    dispatch_run=dispatch_run,
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
    user_role_service = container.build_user_role_service()
    bot_texts_service = container.build_bot_texts_service()

    dlq_producer, consumer = _create_kafka_clients(config)
    logger.info(
        "Kafka consumer started", extra={"topic": config.kafka.kafka_topic}
    )

    bot = Bot(token=config.bot.bot_token)
    messenger_clients: dict[str, MessengerClient] = {
        "telegram": TelegramMessengerClient(bot),
    }
    tracked_clients: dict[str, MessengerClient] = {
        "telegram": TelegramMessengerClient(bot, retry_attempts=1),
    }
    max_session: aiohttp.ClientSession | None = None
    if config.max_bot and config.max_bot.token:
        max_session = aiohttp.ClientSession()
        messenger_clients["max"] = MaxMessengerClient(
            token=config.max_bot.token, session=max_session
        )
        tracked_clients["max"] = MaxMessengerClient(
            token=config.max_bot.token, session=max_session, retry_attempts=1
        )
    try:
        await _consume_forever(
            consumer=consumer,
            dlq_producer=dlq_producer,
            bot=bot,
            messenger_clients=messenger_clients,
            offer_dispatch_service=offer_dispatch_service,
            config=config,
            bot_texts_service=bot_texts_service,
            default_locale=config.market.default_locale,
            user_role_service=user_role_service,
            tracked_clients=tracked_clients,
        )
    finally:
        if max_session:
            await max_session.close()
        await container.dispose()


def main() -> None:
    """Entry point."""
    asyncio.run(run_consumer())


if __name__ == "__main__":  # pragma: no cover
    main()
