# Настройка HTTPS для Instagram Webhook

Эта конфигурация настраивает Nginx как reverse proxy с SSL сертификатами от Let's Encrypt для Instagram webhook.

## Домен не захардкожен

Конфигурация не привязана к конкретному домену. На любом сервере достаточно задать переменную **DOMAIN** (и **WEBHOOK_BASE_URL** с тем же доменом) в `.env` — nginx подставит домен в пути к SSL-сертификатам при старте контейнера. Prometheus и Grafana также используют DOMAIN для своих URL.

В `config/env.example` задайте:
- `DOMAIN=ваш-домен.example.com`
- `WEBHOOK_BASE_URL=https://ваш-домен.example.com`

После получения сертификата для этого домена (см. ниже) развёртывание будет работать без правок конфигов nginx.

## Dev-контур

Для dev задайте домен через переменную (по умолчанию в override — dev.usemycontent.ru):

```bash
DOMAIN=dev.usemycontent.ru docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

Либо укажите DOMAIN в `.env`. Сертификаты должны быть получены для этого домена (например, через `init-letsencrypt.sh` с `domains=(dev.usemycontent.ru)`).

Если на окружении нет SSL вообще (нет домена и сертификатов), используйте `nginx/nginx-http-only.conf` и монтируйте его вместо `nginx.conf` (только HTTP, порт 80).

## Предварительные требования

1. Домен, который указывает на IP вашего сервера (A-запись)
2. Порты 80 и 443 открыты в firewall
3. Docker и Docker Compose установлены

## Шаги настройки

### 1. Обновите конфигурацию

- В **.env** задайте `DOMAIN=ваш-домен.example.com` и `WEBHOOK_BASE_URL=https://ваш-домен.example.com` (скопируйте из `config/env.example` при необходимости).
- В **nginx/init-letsencrypt.sh** задайте `domains=(ваш-домен.example.com)` и `email="ваш@email"`.

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
