# Структурированное логирование

## Обзор

Приложение использует структурированное логирование для улучшения отладки и мониторинга. В продакшене логи выводятся в JSON-формате, что упрощает их обработку системами мониторинга и анализа.

## Конфигурация

### Переменные окружения

- `LOG_LEVEL` - уровень логирования (DEBUG, INFO, WARNING, ERROR, CRITICAL). По умолчанию: `INFO`
- `LOG_FORMAT` - формат логирования (`json` или `text`). По умолчанию: `text`

### Пример конфигурации

```bash
# Текстовый формат (для разработки)
LOG_LEVEL=DEBUG
LOG_FORMAT=text

# JSON формат (для продакшена)
LOG_LEVEL=INFO
LOG_FORMAT=json
```

## Формат логов

### Текстовый формат

```
2026-01-21 15:30:45,123 INFO ugc_bot.application.services.order_service - Order created
```

### JSON формат

```json
{
  "timestamp": "2026-01-21T15:30:45.123456",
  "level": "INFO",
  "logger": "ugc_bot.application.services.order_service",
  "message": "Order created",
  "order_id": "550e8400-e29b-41d4-a716-446655440000",
  "advertiser_id": "660e8400-e29b-41d4-a716-446655440001",
  "price": 15000.0,
  "bloggers_needed": 3,
  "event_type": "order.created"
}
```

## Критические события

### Создание заказа (`order.created`)

**Уровень:** `INFO`

**Контекст:**
- `order_id` - UUID заказа
- `advertiser_id` - UUID рекламодателя
- `price` - цена заказа (float)
- `bloggers_needed` - количество требуемых блогеров (int)
- `event_type` - `"order.created"`

**Пример:**
```python
logger.info(
    "Order created",
    extra={
        "order_id": str(order.order_id),
        "advertiser_id": str(order.advertiser_id),
        "price": float(order.price),
        "bloggers_needed": order.bloggers_needed,
        "event_type": "order.created",
    },
)
```

### Подтверждение оплаты (`payment.confirmed`)

**Уровень:** `INFO`

**Контекст:**
- `payment_id` - UUID платежа
- `order_id` - UUID заказа
- `user_id` - UUID пользователя
- `amount` - сумма платежа (float)
- `currency` - валюта (str)
- `external_id` - внешний ID платежа (str)
- `event_type` - `"payment.confirmed"`

**Пример:**
```python
logger.info(
    "Payment confirmed",
    extra={
        "payment_id": str(payment.payment_id),
        "order_id": str(order_id),
        "user_id": str(user_id),
        "amount": float(payment.amount),
        "currency": payment.currency,
        "external_id": payment.external_id,
        "event_type": "payment.confirmed",
    },
)
```

### Блокировка пользователя (`user.blocked`)

**Уровень:** `WARNING`

**Контекст:**
- `user_id` - UUID пользователя
- `external_id` - внешний ID пользователя (str)
- `username` - имя пользователя (str)
- `previous_status` - предыдущий статус (str)
- `event_type` - `"user.blocked"`

**Пример:**
```python
logger.warning(
    "User blocked",
    extra={
        "user_id": str(user.user_id),
        "external_id": user.external_id,
        "username": user.username,
        "previous_status": user.status.value,
        "event_type": "user.blocked",
    },
)
```

### Блокировка через админку (`user.blocked.admin`)

**Уровень:** `WARNING`

**Контекст:**
- `user_id` - UUID пользователя
- `external_id` - внешний ID пользователя (str)
- `username` - имя пользователя (str)
- `previous_status` - предыдущий статус (str или None)
- `event_type` - `"user.blocked.admin"`

### Создание жалобы (`complaint.created`)

**Уровень:** `WARNING`

**Контекст:**
- `complaint_id` - UUID жалобы
- `reporter_id` - UUID пользователя, подавшего жалобу
- `reported_id` - UUID пользователя, на которого пожаловались
- `order_id` - UUID заказа
- `reason` - причина жалобы (str)
- `event_type` - `"complaint.created"`

**Пример:**
```python
logger.warning(
    "Complaint created",
    extra={
        "complaint_id": str(complaint.complaint_id),
        "reporter_id": str(reporter_id),
        "reported_id": str(reported_id),
        "order_id": str(order_id),
        "reason": reason,
        "event_type": "complaint.created",
    },
)
```

### Отклонение жалобы (`complaint.dismissed`)

**Уровень:** `INFO`

**Контекст:**
- `complaint_id` - UUID жалобы
- `reporter_id` - UUID пользователя, подавшего жалобу
- `reported_id` - UUID пользователя, на которого пожаловались
- `order_id` - UUID заказа
- `event_type` - `"complaint.dismissed"`

### Принятие мер по жалобе (`complaint.action_taken`)

**Уровень:** `WARNING`

**Контекст:**
- `complaint_id` - UUID жалобы
- `reporter_id` - UUID пользователя, подавшего жалобу
- `reported_id` - UUID пользователя, на которого пожаловались
- `order_id` - UUID заказа
- `reason` - причина жалобы (str)
- `event_type` - `"complaint.action_taken"`

### Ручное разрешение ISSUE (`interaction.issue_resolved`)

**Уровень:** `INFO`

**Контекст:**
- `interaction_id` - UUID взаимодействия
- `order_id` - UUID заказа
- `blogger_id` - UUID блогера
- `advertiser_id` - UUID рекламодателя
- `final_status` - финальный статус (OK или NO_DEAL)
- `event_type` - `"interaction.issue_resolved"`

**Пример:**
```python
logger.info(
    "Interaction issue manually resolved",
    extra={
        "interaction_id": str(interaction.interaction_id),
        "order_id": str(interaction.order_id),
        "blogger_id": str(interaction.blogger_id),
        "advertiser_id": str(interaction.advertiser_id),
        "final_status": final_status.value,
        "event_type": "interaction.issue_resolved",
    },
)
```

## Использование в коде

### Базовый пример

```python
import logging

logger = logging.getLogger(__name__)

logger.info(
    "Event occurred",
    extra={
        "user_id": str(user.user_id),
        "order_id": str(order.order_id),
        "event_type": "custom.event",
    },
)
```

### Обработка ошибок

```python
try:
    # Some operation
    pass
except Exception as e:
    logger.exception(
        "Operation failed",
        extra={
            "user_id": str(user.user_id),
            "error": str(e),
            "event_type": "operation.failed",
        },
    )
```

## Интеграция с системами мониторинга

JSON-формат логов позволяет легко интегрировать их с системами мониторинга:

- **ELK Stack (Elasticsearch, Logstash, Kibana)** - для анализа и визуализации
- **Prometheus + Grafana** - для метрик и дашбордов
- **Sentry** - для отслеживания ошибок
- **Datadog** - для комплексного мониторинга

## ELK Stack

Проект включает настроенный ELK стек для централизованного сбора и анализа логов.

### Компоненты

- **Elasticsearch** (порт 9200) - хранилище и поиск по логам
- **Kibana** (порт 5601) - веб-интерфейс для визуализации и анализа
- **Filebeat** - сбор логов из Docker контейнеров

### Запуск ELK стека

ELK стек автоматически запускается вместе с приложением:

```bash
docker compose up -d
```

После запуска:
- Elasticsearch будет доступен по адресу: http://localhost:9200
- Kibana будет доступна по адресу: http://localhost:5601

### Настройка индексов в Kibana

1. Откройте Kibana: http://localhost:5601
2. Перейдите в **Stack Management** → **Index Patterns**
3. Создайте индекс-паттерн: `ugc-logs-*`
4. Выберите поле времени: `@timestamp` или `timestamp`
5. Нажмите **Create index pattern**

### Просмотр логов

1. Перейдите в **Discover** в Kibana
2. Выберите индекс-паттерн `ugc-logs-*`
3. Используйте фильтры для поиска:
   - По уровню: `level: "ERROR"`
   - По типу события: `event_type: "order.created"`
   - По сервису: `container.name: "app"`

### Конфигурация

Логи автоматически собираются из всех контейнеров приложения. Для корректной работы:

1. Убедитесь, что `LOG_FORMAT=json` в `.env` файле
2. Filebeat автоматически парсит JSON логи и отправляет их в Elasticsearch
3. Логи индексируются по дате: `ugc-logs-YYYY.MM.DD`

### Примеры запросов в Kibana

**Все ошибки:**
```
level: "ERROR"
```

**Созданные заказы за последний час:**
```
event_type: "order.created" AND @timestamp:[now-1h TO now]
```

**Логи конкретного сервиса:**
```
container.name: "kafka_consumer"
```

**Логи с определенным order_id:**
```
order_id: "550e8400-e29b-41d4-a716-446655440000"
```

### Пример парсинга JSON логов

```python
import json
import sys

for line in sys.stdin:
    log_entry = json.loads(line)
    if log_entry.get("event_type") == "order.created":
        print(f"New order: {log_entry['order_id']}")
```

## Рекомендации

1. **Всегда используйте `event_type`** для категоризации событий
2. **Включайте контекстные ID** (user_id, order_id, interaction_id) для трассировки
3. **Используйте правильный уровень логирования:**
   - `DEBUG` - детальная информация для отладки
   - `INFO` - информационные события (создание заказа, оплата)
   - `WARNING` - предупреждения (блокировка, жалобы)
   - `ERROR` - ошибки, требующие внимания
   - `CRITICAL` - критические ошибки, требующие немедленного вмешательства

4. **Не логируйте чувствительные данные** (пароли, токены, персональные данные)
5. **Используйте структурированные данные** в поле `extra` для лучшей обработки
