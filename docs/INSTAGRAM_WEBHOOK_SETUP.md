# Настройка Instagram Webhooks для обработки сообщений

## Требования согласно документации Meta

Согласно [официальной документации](https://developers.facebook.com/docs/instagram-platform/webhooks), для обработки сообщений Instagram необходимо:

### 1. Настройка приложения в Meta App Dashboard

1. **Приложение должно быть в режиме Live** - только Live приложения получают webhook уведомления
2. **Требуется Advanced Access** для поля `messages`
3. **Требуется Business Verification** для Instagram Messaging API
4. **Нужны правильные permissions:**
   - `instagram_basic`
   - `instagram_manage_messages`
   - `pages_manage_metadata`
   - `pages_read_engagement`
   - `pages_show_list`

### 2. Настройка Webhook в App Dashboard

1. Перейдите в **App Dashboard → Products → Webhooks**
2. Добавьте **Callback URL**: `https://bot.usemycontent.ru/webhook/instagram`
3. Установите **Verify Token**: значение из `INSTAGRAM_WEBHOOK_VERIFY_TOKEN` в `.env`
4. Подпишитесь на поле **`messages`** для объекта **`instagram`**

### 3. Подписка через API

После настройки в Dashboard, нужно включить подписки через API:

```bash
POST https://graph.instagram.com/v24.0/<PAGE_ID>/subscribed_apps
  ?subscribed_fields=messages
  &access_token=<ACCESS_TOKEN>
```

Или для текущего пользователя:

```bash
POST https://graph.instagram.com/v24.0/me/subscribed_apps
  ?subscribed_fields=messages
  &access_token=<ACCESS_TOKEN>
```

### 4. Структура payload для messages

Согласно документации, payload для сообщений имеет структуру:

```json
{
  "object": "instagram",
  "entry": [
    {
      "id": "<PAGE_ID>",
      "time": 1234567890,
      "messaging": [
        {
          "sender": {"id": "<INSTAGRAM_USER_ID>"},
          "recipient": {"id": "<PAGE_ID>"},
          "timestamp": 1234567890,
          "message": {
            "mid": "<MESSAGE_ID>",
            "text": "ABC123XY"
          }
        }
      ]
    }
  ]
}
```

### 5. Дополнительные поля для подписки

Можно подписаться на дополнительные поля:
- `messages` - входящие сообщения
- `message_echoes` - эхо-сообщения (сообщения, отправленные через API)
- `message_reactions` - реакции на сообщения
- `messaging_postbacks` - postback кнопки
- `messaging_optins` - подписки на уведомления

## Текущая реализация

Текущая реализация уже включает:
- ✅ Верификацию webhook (GET `/webhook/instagram`)
- ✅ Валидацию подписи (X-Hub-Signature-256)
- ✅ Обработку событий (POST `/webhook/instagram`)
- ✅ Обработку сообщений из поля `messaging`
- ✅ Верификацию кодов через Instagram Graph API

## Что нужно сделать дополнительно

### 1. Подписаться на поле `messages` через API

Используйте готовый скрипт:

```bash
# Подписаться на поле messages
uv run python scripts/subscribe_instagram_webhook.py

# Или для конкретной страницы
uv run python scripts/subscribe_instagram_webhook.py --page-id YOUR_PAGE_ID

# Проверить текущие подписки
uv run python scripts/subscribe_instagram_webhook.py --list
```

Скрипт автоматически:
- Загружает `INSTAGRAM_ACCESS_TOKEN` из `.env`
- Отправляет POST запрос к `/me/subscribed_apps` или `/<PAGE_ID>/subscribed_apps`
- Подписывается на поле `messages`

### 2. Убедиться, что приложение в режиме Live

В Meta App Dashboard:
- **App Review → Permissions and Features**
- Убедитесь, что все необходимые permissions одобрены
- Переключите приложение в режим **Live**

### 3. Проверить настройки Webhook

В Meta App Dashboard:
- **Products → Webhooks → Instagram**
- Убедитесь, что Callback URL правильный
- Проверьте, что подписаны на поле `messages`

## Тестирование

1. Отправьте тестовое сообщение на Instagram страницу
2. Проверьте логи: `docker-compose logs instagram_webhook`
3. Проверьте, что сообщение обработано и код верифицирован

## Troubleshooting

### Webhook не получает события

- Проверьте, что приложение в режиме Live
- Проверьте, что подписки включены через API
- Проверьте логи на наличие ошибок

### Сообщения не обрабатываются

- Проверьте структуру payload в логах
- Убедитесь, что поле `messages` подписано
- Проверьте, что `object` равен `"instagram"`
