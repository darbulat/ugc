# Быстрый старт: Настройка HTTPS для Instagram Webhook

⚠️ **ВАЖНО**: Let's Encrypt не выдает сертификаты для IP-адресов! Нужен домен. Если у вас только IP, см. [FIX_IP_ERROR.md](./FIX_IP_ERROR.md).

## Автоматическая настройка (рекомендуется)

```bash
cd nginx
./setup-ssl.sh
```

Скрипт запросит:
- Домен (например: `webhook.example.com`)
- Email для Let's Encrypt

После этого выполните:
```bash
./init-letsencrypt.sh
docker-compose up -d
```

## Ручная настройка

### 1. Обновите конфигурацию

В файле `nginx/nginx.conf` замените `YOUR_DOMAIN` на ваш домен:
```bash
sed -i 's/YOUR_DOMAIN/your-domain.com/g' nginx/nginx.conf
```

В файле `nginx/init-letsencrypt.sh` замените:
- `YOUR_DOMAIN` на ваш домен
- `YOUR_EMAIL` на ваш email

### 2. Убедитесь, что домен указывает на сервер

```bash
dig +short your-domain.com
# Должен вернуть IP вашего сервера
```

### 3. Откройте порты в firewall

```bash
# Ubuntu/Debian
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# CentOS/RHEL
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --reload
```

### 4. Получите SSL сертификат

```bash
./nginx/init-letsencrypt.sh
```

### 5. Запустите сервисы

```bash
docker-compose up -d
```

### 6. Проверьте работу

```bash
curl -I https://your-domain.com/webhook/instagram
```

Должен вернуть `200 OK` или `400 Bad Request` (это нормально, если нет правильных параметров).

## Настройка в Instagram

1. Перейдите в [Facebook Developers](https://developers.facebook.com/)
2. Выберите ваше приложение
3. Перейдите в Instagram → Webhooks
4. Добавьте webhook:
   - **Callback URL**: `https://your-domain.com/webhook/instagram`
   - **Verify Token**: значение из `INSTAGRAM_WEBHOOK_VERIFY_TOKEN` в `.env`
5. Подпишитесь на события: `messages`

## Проверка работы

```bash
# Проверка SSL сертификата
openssl s_client -connect your-domain.com:443 -servername your-domain.com

# Проверка webhook endpoint
curl -X GET "https://your-domain.com/webhook/instagram?hub.mode=subscribe&hub.challenge=test&hub.verify_token=YOUR_TOKEN"
```

## Troubleshooting

### Nginx не запускается
```bash
docker-compose logs nginx
docker-compose exec nginx nginx -t
```

### Сертификат не получен
- Убедитесь, что домен указывает на IP сервера
- Убедитесь, что порт 80 открыт
- Проверьте логи: `docker-compose logs certbot`

### Webhook не работает
- Проверьте логи: `docker-compose logs instagram_webhook`
- Проверьте, что `INSTAGRAM_WEBHOOK_VERIFY_TOKEN` совпадает в `.env` и настройках Instagram
