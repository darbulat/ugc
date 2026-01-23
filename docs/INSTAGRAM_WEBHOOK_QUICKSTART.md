# Быстрый старт: Настройка Instagram Webhooks

## Шаги настройки

### 1. Настройка в Meta App Dashboard

1. Перейдите в [Meta App Dashboard](https://developers.facebook.com/apps/)
2. Выберите ваше приложение
3. **Products → Webhooks → Instagram**
4. Нажмите **"Add Callback URL"**
5. Введите:
   - **Callback URL**: `https://bot.usemycontent.ru/webhook/instagram`
   - **Verify Token**: значение из `INSTAGRAM_WEBHOOK_VERIFY_TOKEN` в `.env` (например: `8aAywMqtmtDdJjT`)
6. Нажмите **"Verify and Save"**
7. После успешной верификации, подпишитесь на поле **`messages`**

### 2. Подписка через API

После настройки в Dashboard, включите подписки через API:

```bash
# Подписаться на поле messages
uv run python scripts/subscribe_instagram_webhook.py

# Проверить подписки
uv run python scripts/subscribe_instagram_webhook.py --list
```

### 3. Убедитесь, что приложение в режиме Live

**Важно**: Webhook события приходят только для приложений в режиме **Live**.

1. В App Dashboard: **App Review → Permissions and Features**
2. Убедитесь, что все необходимые permissions одобрены:
   - `instagram_basic`
   - `instagram_manage_messages`
   - `pages_manage_metadata`
   - `pages_read_engagement`
   - `pages_show_list`
3. Переключите приложение в режим **Live**

### 4. Проверка работы

1. Отправьте тестовое сообщение на вашу Instagram страницу
2. Проверьте логи:
   ```bash
   docker-compose logs instagram_webhook | tail -50
   ```
3. Должны увидеть:
   - `Processing Instagram message`
   - `Instagram verification successful via webhook` (если код валидный)

## Текущая реализация

✅ **Уже реализовано:**
- Верификация webhook (GET запрос)
- Валидация подписи (SHA256)
- Обработка сообщений из поля `messaging`
- Фильтрация echo/self сообщений
- Верификация кодов через Instagram Graph API
- Уведомления пользователей в Telegram

## Структура обработки

1. **Webhook получает событие** → `POST /webhook/instagram`
2. **Валидация подписи** → проверка `X-Hub-Signature-256`
3. **Парсинг payload** → извлечение `messaging` событий
4. **Фильтрация** → пропуск echo/self сообщений
5. **Верификация кода** → проверка кода и username через Graph API
6. **Подтверждение профиля** → установка `confirmed=True`
7. **Уведомление** → отправка сообщения в Telegram

## Troubleshooting

### Webhook не получает события

- ✅ Приложение в режиме Live?
- ✅ Подписки включены через API?
- ✅ Callback URL правильный и доступен?
- ✅ Проверьте логи: `docker-compose logs instagram_webhook`

### Сообщения не обрабатываются

- ✅ Проверьте структуру payload в логах
- ✅ Убедитесь, что поле `messages` подписано
- ✅ Проверьте, что `object` равен `"instagram"`
- ✅ Убедитесь, что сообщения не echo/self (они пропускаются)

### Ошибки верификации

- ✅ Проверьте `INSTAGRAM_ACCESS_TOKEN` в `.env`
- ✅ Убедитесь, что токен имеет права `instagram_manage_messages`
- ✅ Проверьте логи Graph API запросов
