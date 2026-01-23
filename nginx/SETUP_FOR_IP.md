# Настройка HTTPS для IP-адреса

⚠️ **Важно**: Let's Encrypt не выдает сертификаты для IP-адресов. Instagram webhooks требуют валидный SSL сертификат.

## Варианты решения:

### Вариант 1: Использовать доменное имя (РЕКОМЕНДУЕТСЯ)

1. **Получите домен** (можно бесплатный от Freenom, или купить на Namecheap/GoDaddy)
2. **Настройте DNS**: Создайте A-запись, указывающую на ваш IP
   ```
   webhook.yourdomain.com  A  31.59.106.143
   ```
3. **Обновите конфигурацию**:
   ```bash
   cd nginx
   ./setup-ssl.sh  # Укажите webhook.yourdomain.com
   ./init-letsencrypt.sh
   ```

### Вариант 2: Самоподписанный сертификат (только для тестирования)

⚠️ **Внимание**: Instagram может не принимать самоподписанные сертификаты!

```bash
cd nginx
./generate-self-signed.sh 31.59.106.143
```

Затем обновите `nginx/nginx.conf`:
```nginx
ssl_certificate /etc/letsencrypt/live/31_59_106_143/fullchain.pem;
ssl_certificate_key /etc/letsencrypt/live/31_59_106_143/privkey.pem;
```

И обновите docker-compose.yml, чтобы монтировать локальную директорию:
```yaml
nginx:
  volumes:
    - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
    - ./certbot/conf:/etc/letsencrypt:ro  # Изменить на локальную директорию
    - certbot_www:/var/www/certbot
```

### Вариант 3: Использовать Cloudflare или другой CDN

1. Зарегистрируйте домен
2. Настройте Cloudflare (бесплатный план)
3. Используйте Cloudflare SSL (Flexible или Full)
4. Настройте webhook на домен через Cloudflare

### Вариант 4: Использовать ngrok или подобный сервис (для разработки)

```bash
# Установите ngrok
ngrok http 8002

# Используйте HTTPS URL от ngrok в настройках Instagram webhook
```

## Рекомендация

Для продакшн-использования **обязательно используйте доменное имя** с валидным SSL сертификатом от Let's Encrypt. Instagram требует валидный SSL для webhooks.
