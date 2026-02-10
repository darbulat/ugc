# Настройка HTTPS для Instagram Webhook

Эта конфигурация настраивает Nginx как reverse proxy с SSL сертификатами от Let's Encrypt для Instagram webhook.

## Dev-контур (dev.usemycontent.ru)

На dev используется тот же HTTPS, но сертификаты для домена **dev.usemycontent.ru** (файл `nginx/ssl_cert_dev.conf`). Запуск:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

На dev-сервере должны быть получены сертификаты для `dev.usemycontent.ru` (например, через `init-letsencrypt.sh` с этим доменом). Сервисы доступны по `https://dev.usemycontent.ru/...`.

Если на окружении нет SSL вообще (нет домена и сертификатов), используйте `nginx/nginx-http-only.conf` и монтируйте его вместо `nginx.conf` (только HTTP, порт 80).

## Предварительные требования

1. Домен, который указывает на IP вашего сервера (A-запись)
2. Порты 80 и 443 открыты в firewall
3. Docker и Docker Compose установлены

## Шаги настройки

### 1. Обновите конфигурацию

Отредактируйте файлы:
- `nginx/nginx.conf` - замените `YOUR_DOMAIN` на ваш домен
- `nginx/init-letsencrypt.sh` - замените `YOUR_DOMAIN` и `YOUR_EMAIL` на ваши значения

### 2. Запустите инициализацию SSL

```bash
./nginx/init-letsencrypt.sh
```

Этот скрипт:
- Создаст временный SSL сертификат
- Запустит Nginx
- Получит реальный сертификат от Let's Encrypt
- Перезагрузит Nginx

### 3. Запустите все сервисы

```bash
docker-compose up -d
```

### 4. Проверьте работу

Webhook будет доступен по адресу:
```
https://YOUR_DOMAIN/webhook/instagram
```

Проверьте SSL:
```bash
curl -I https://YOUR_DOMAIN/webhook/instagram
```

## Обновление сертификатов

Certbot автоматически обновляет сертификаты каждые 12 часов. Nginx перезагружается автоматически после обновления.

Для ручного обновления:
```bash
docker-compose run --rm certbot renew
docker-compose exec nginx nginx -s reload
```

## Настройка в Instagram

В настройках Instagram Webhook укажите:
- **Callback URL**: `https://YOUR_DOMAIN/webhook/instagram`
- **Verify Token**: значение из `INSTAGRAM_WEBHOOK_VERIFY_TOKEN` в `.env`

## Troubleshooting

### Проверка логов Nginx
```bash
docker-compose logs nginx
```

### Проверка логов Certbot
```bash
docker-compose logs certbot
```

### Проверка конфигурации Nginx
```bash
docker-compose exec nginx nginx -t
```

### Ручная проверка SSL
```bash
openssl s_client -connect YOUR_DOMAIN:443 -servername YOUR_DOMAIN
```

## Безопасность

- SSL сертификаты автоматически обновляются
- HTTP трафик перенаправляется на HTTPS
- Настроены security headers (HSTS, X-Frame-Options, etc.)
- Используются современные TLS протоколы (TLSv1.2, TLSv1.3)
