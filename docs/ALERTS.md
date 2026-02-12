# Настройка алертов

## Обзор

Система мониторинга использует Prometheus для сбора метрик и Alertmanager для отправки уведомлений об алертах. Уведомления отправляются в Telegram.

## Архитектура

```
Prometheus → Alertmanager → Telegram Bot
Loki Ruler → Alertmanager → Telegram Bot
```

- **Prometheus** собирает метрики и проверяет правила алертов
- **Loki Ruler** проверяет правила на основе логов (необработанные ошибки)
- **Alertmanager** обрабатывает алерты и отправляет уведомления
- **Telegram** используется как канал доставки уведомлений

## Настройка переменных окружения

Для работы алертов необходимо настроить следующие переменные в `.env`:

```bash
# Telegram Bot для отправки алертов
TELEGRAM_BOT_TOKEN=your_telegram_bot_token

# Обычный чат для всех алертов (warning и critical)
TELEGRAM_CHAT_ID=your_chat_id

# Отдельный чат только для критических алертов
TELEGRAM_CRITICAL_CHAT_ID=your_critical_chat_id
```

### Получение токена бота

1. Создайте бота через [@BotFather](https://t.me/BotFather) в Telegram
2. Получите токен бота
3. Добавьте токен в `TELEGRAM_BOT_TOKEN`

### Получение Chat ID

1. Добавьте бота в группу или начните диалог
2. Отправьте любое сообщение боту
3. Откройте в браузере: `https://api.telegram.org/bot<BOT_TOKEN>/getUpdates`
4. Найдите `chat.id` в ответе
5. Добавьте ID в `TELEGRAM_CHAT_ID` и `TELEGRAM_CRITICAL_CHAT_ID`

## Конфигурация Alertmanager

Файл конфигурации: `config/monitoring/alertmanager.yml`

### Маршрутизация алертов

- **Warning алерты** → отправляются в `TELEGRAM_CHAT_ID`
- **Critical алерты** → отправляются в `TELEGRAM_CRITICAL_CHAT_ID`

### Параметры группировки

- `group_wait: 30s` - время ожидания перед отправкой первой группы алертов
- `group_interval: 5m` - интервал между отправками групп алертов
- `repeat_interval: 4h` - интервал повторной отправки нерешенных алертов

### Правила подавления (Inhibit Rules)

Критические алерты подавляют предупреждения для того же инстанса и типа алерта.

## Существующие алерты

### Хост-метрики

#### HostHighCpuLoad
- **Тип:** Warning
- **Условие:** CPU usage > 85% в течение 5 минут
- **Описание:** Высокая загрузка CPU на хосте

#### HostOutOfMemory
- **Тип:** Critical
- **Условие:** Доступная память < 10% в течение 5 минут
- **Описание:** Критически низкий объем доступной памяти

#### HostLowDiskSpace
- **Тип:** Warning
- **Условие:** Свободное место на диске < 15% в течение 10 минут
- **Описание:** Мало свободного места на диске

### Алерты приложения (Critical → page)

#### ApplicationDown
- **Тип:** Critical
- **Условие:** `up{job="ugc-bot"} == 0` в течение 2 минут
- **Описание:** Приложение недоступно

#### ApplicationHighErrorRate
- **Тип:** Critical
- **Условие:** Более 10 ошибок/сек за 5 минут
- **Описание:** Высокий уровень ошибок в приложении

#### SLOErrorBudgetBurnRateFast
- **Тип:** Critical
- **Условие:** Burn rate 14.4x (1h) или 6x (6h) — потребление 2%/5% error budget
- **Описание:** SLO 99.9%, быстрое сжигание error budget (Google SRE)

#### HighPaymentFailureRate
- **Тип:** Critical
- **Условие:** Более 10% неудачных платежей за 15 минут
- **Описание:** Высокий уровень неудачных платежей

### Алерты приложения (Warning → ticket)

#### SLOErrorBudgetBurnRateSlow
- **Тип:** Warning
- **Условие:** Burn rate 1x за 3 дня — потребление 10% error budget
- **Описание:** Медленное сжигание error budget

#### ApplicationHighLatency
- **Тип:** Warning
- **Условие:** p95 HTTP latency > 2s за 10 минут
- **Описание:** Высокая латентность запросов

#### RegistrationDrop
- **Тип:** Warning
- **Условие:** Падение регистраций > 50% относительно вчера
- **Описание:** Резкое снижение регистраций

#### HighComplaintRate
- **Тип:** Warning
- **Условие:** Рост жалоб более чем в 2 раза относительно вчера
- **Описание:** Аномальный рост жалоб

### Telegram-специфичные алерты

#### TelegramWebhookRejectRate
- **Тип:** Warning
- **Условие:** Более 10% webhook-запросов вернули 4xx за 15 минут
- **Описание:** Высокий процент отклонённых webhook

#### TelegramRateLimitHit
- **Тип:** Warning
- **Условие:** Хотя бы один rate limit hit за 5 минут
- **Описание:** Срабатывание rate limit Telegram API

#### TelegramApiErrors
- **Тип:** Critical
- **Условие:** Более 0.1 ошибок Telegram API/сек за 5 минут
- **Описание:** Ошибки при вызове Telegram API

### Репликация

Метрики PostgreSQL (в т.ч. слоты логической репликации) собираются postgres_exporter; алерты срабатывают при проблемах с репликацией на Beget.

#### ReplicationSlotInactive
- **Тип:** Warning
- **Условие:** Хотя бы один слот логической репликации неактивен в течение 5 минут
- **Описание:** Подписчик (например, Beget) отключён или не может подключиться к издателю (локальная БД). Проверить доступность издателя с Beget, состояние subscription на стороне Beget и логи PostgreSQL.

### Алерты на необработанные ошибки (Loki)

#### UnhandledErrorInService
- **Тип:** Critical
- **Источник:** Loki Ruler (правила в `config/monitoring/loki-alerts/`)
- **Условие:** В логах сервиса обнаружен Traceback или "Exception was never retrieved" в течение 5 минут
- **Сервисы:** app, app_2, instagram_webhook, kafka_consumer, feedback_scheduler, outbox_processor
- **Описание:** Необработанное исключение в указанном сервисе

Для обнаружения необработанных ошибок используются:
- **Exception hooks** в CLI-сервисах (kafka_consumer, feedback_scheduler, outbox_processor) — логирование через `logger.exception` перед падением
- **Exception handler** в FastAPI-приложениях (telegram_webhook_app, instagram_webhook_app) — глобальный перехватчик `Exception`

## Добавление новых алертов

### 1. Редактирование файла правил

Откройте `config/monitoring/alerts.yml` и добавьте новое правило:

```yaml
groups:
  - name: application
    rules:
      - alert: ApplicationHighErrorRate
        expr: rate(ugc_errors_total[5m]) > 10
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: High error rate in application
          description: Error rate is {{ $value }} errors/sec for 5 minutes.
```

### 2. Структура правила алерта

```yaml
- alert: AlertName          # Уникальное имя алерта
  expr: promql_expression   # PromQL выражение для проверки
  for: 5m                   # Время, в течение которого условие должно быть истинным
  labels:                   # Метки для маршрутизации
    severity: warning       # warning или critical
  annotations:              # Описание алерта
    summary: Краткое описание
    description: Подробное описание с деталями
```

### 3. Recording rules (SLI/SLO)

Recording rules для SLO-based alerting находятся в `config/monitoring/recording_rules.yml`. Они вычисляют `job:slo_errors:ratio_rate*` для окон 5m, 30m, 1h, 2h, 6h, 24h, 3d. Файл смонтирован в Prometheus вместе с `alerts.yml`.

### 4. Перезапуск Prometheus

После изменения правил перезапустите Prometheus:

```bash
docker compose restart prometheus
```

Или перезагрузите конфигурацию через API:

```bash
curl -X POST http://localhost:9090/-/reload
```

### 5. Правила Loki (логи)

Правила для алертов на необработанные ошибки находятся в `config/monitoring/loki-alerts/fake/unhandled_errors.yml`. После изменения перезапустите Loki:

```bash
docker compose restart loki
```

## Примеры алертов для приложения

### Высокий уровень ошибок

```yaml
- alert: ApplicationHighErrorRate
  expr: rate(ugc_errors_total[5m]) > 10
  for: 5m
  labels:
    severity: critical
  annotations:
    summary: High error rate detected
    description: Application error rate is {{ $value }} errors/sec
```

### Отсутствие метрик приложения

```yaml
- alert: ApplicationMetricsMissing
  expr: up{job="ugc-bot"} == 0
  for: 2m
  labels:
    severity: critical
  annotations:
    summary: Application metrics endpoint is down
    description: Cannot scrape metrics from ugc-bot for 2 minutes
```

### Высокая латентность запросов

```yaml
- alert: ApplicationHighLatency
  expr: histogram_quantile(0.95, rate(ugc_request_latency_seconds_bucket[5m])) > 2
  for: 10m
  labels:
    severity: warning
  annotations:
    summary: High request latency detected
    description: 95th percentile latency is {{ $value }}s
```

### Резкое снижение регистраций

```yaml
- alert: RegistrationDrop
  expr: |
    (
      rate(ugc_blogger_registrations_total[1h]) +
      rate(ugc_advertiser_registrations_total[1h])
    ) < (
      rate(ugc_blogger_registrations_total[1h] offset 24h) +
      rate(ugc_advertiser_registrations_total[1h] offset 24h)
    ) * 0.5
  for: 1h
  labels:
    severity: warning
  annotations:
    summary: Significant drop in registrations
    description: Registration rate dropped by more than 50% compared to yesterday
```

### Высокий уровень неудачных платежей

```yaml
- alert: HighPaymentFailureRate
  expr: |
    rate(ugc_payment_failed_total[15m]) /
    (rate(ugc_orders_created_total[15m]) + 1) > 0.1
  for: 15m
  labels:
    severity: critical
  annotations:
    summary: High payment failure rate
    description: Payment failure rate is {{ $value | humanizePercentage }}
```

### Проблемы с базой данных

```yaml
- alert: DatabaseConnectionIssues
  expr: pg_stat_database_numbackends{datname="ugc"} > 50
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: High number of database connections
    description: Database has {{ $value }} active connections
```

## Тестирование алертов

### Проверка правил в Prometheus

1. Откройте Prometheus UI: `http://localhost:9090`
2. Перейдите в раздел "Alerts"
3. Проверьте статус алертов (Pending/Firing)

### Ручной тест алерта

Используйте Alertmanager v2 API для отправки тестового алерта:

```bash
curl -H "Content-Type: application/json" -d '[
  {
    "labels": {
      "alertname": "TestAlert",
      "severity": "warning",
      "instance": "test"
    },
    "annotations": {
      "summary": "Test alert",
      "description": "This is a test alert"
    }
  }
]' http://localhost:9093/api/v2/alerts
```

> **Примечание:** API v1 (`/api/v1/alerts`) удалён в Alertmanager 0.27.0. Используйте v2 (`/api/v2/alerts`).

### Проверка Alertmanager

1. Откройте Alertmanager UI: `http://localhost:9093`
2. Проверьте статус алертов
3. Убедитесь, что уведомления отправляются в Telegram

## Мониторинг работы алертов

### Проверка статуса сервисов

```bash
# Проверка Prometheus
docker compose ps prometheus

# Проверка Alertmanager
docker compose ps alertmanager

# Просмотр логов Alertmanager
docker compose logs alertmanager
```

### Проверка конфигурации Alertmanager

```bash
# Проверка валидности конфигурации
docker compose exec alertmanager amtool check-config /etc/alertmanager/alertmanager.yml
```

## Рекомендации

1. **Начните с базовых алертов:** Настройте алерты на критичные метрики (ошибки, недоступность сервиса)
2. **Используйте разные чаты:** Разделите warning и critical алерты для лучшей фильтрации
3. **Настройте правильные интервалы:** Избегайте слишком частых уведомлений
4. **Тестируйте алерты:** Регулярно проверяйте работу системы алертов
5. **Документируйте алерты:** Добавляйте понятные описания для каждого алерта
6. **Мониторьте сами алерты:** Настройте алерты на недоступность Prometheus/Alertmanager

## Troubleshooting

### Алерты не отправляются

1. Проверьте переменные окружения:
   ```bash
   docker compose exec alertmanager env | grep TELEGRAM
   ```

2. Проверьте логи Alertmanager:
   ```bash
   docker compose logs alertmanager | grep -i error
   ```

3. Убедитесь, что бот добавлен в чат и имеет права на отправку сообщений

### Алерты отправляются слишком часто

Увеличьте `repeat_interval` в `alertmanager.yml`:

```yaml
repeat_interval: 8h  # Вместо 4h
```

### Алерты не группируются

Проверьте параметры `group_by` в конфигурации маршрута. Убедитесь, что метки в алертах соответствуют группировке.

### Prometheus не видит правила

1. Проверьте, что файл `alerts.yml` смонтирован в контейнер
2. Проверьте синтаксис YAML файла
3. Проверьте логи Prometheus:
   ```bash
   docker compose logs prometheus | grep -i error
   ```

## Дополнительные ресурсы

- [Prometheus Alerting Rules](https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/)
- [Alertmanager Configuration](https://prometheus.io/docs/alerting/latest/configuration/)
- [PromQL Query Language](https://prometheus.io/docs/prometheus/latest/querying/basics/)
