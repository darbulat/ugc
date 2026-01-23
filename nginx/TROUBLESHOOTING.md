# Troubleshooting Let's Encrypt Certificate Issues

## Проблема: "Connection refused" при получении сертификата

Если вы видите ошибку:
```
Detail: 31.59.106.143: Fetching http://bot.usemycontent.ru/.well-known/acme-challenge/...: Connection refused
```

### Проверьте следующие пункты:

#### 1. Домен указывает на правильный IP

```bash
# Проверьте DNS
dig +short bot.usemycontent.ru
# Должен вернуть: 31.59.106.143

# Или
nslookup bot.usemycontent.ru
```

Если IP не совпадает:
- Обновите A-запись в DNS настройках домена
- Подождите распространения DNS (может занять до 24 часов, обычно 5-15 минут)

#### 2. Порт 80 открыт и доступен извне

```bash
# Проверьте, что порт 80 слушается
sudo netstat -tlnp | grep :80
# или
sudo ss -tlnp | grep :80

# Проверьте firewall
sudo ufw status
# Если порт 80 закрыт:
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw reload

# Проверьте извне (с другого сервера или используя онлайн-сервис)
curl -I http://bot.usemycontent.ru/.well-known/acme-challenge/test
```

#### 3. Nginx запущен и слушает на порту 80

```bash
# Проверьте статус контейнера
docker-compose ps nginx

# Проверьте логи
docker-compose logs nginx

# Проверьте, что Nginx слушает на порту 80
docker-compose exec nginx netstat -tlnp | grep :80
```

#### 4. Nginx конфигурация правильная

```bash
# Проверьте синтаксис
docker-compose exec nginx nginx -t

# Убедитесь, что location /.well-known/acme-challenge/ настроен
docker-compose exec nginx cat /etc/nginx/nginx.conf | grep -A 3 "acme-challenge"
```

#### 5. Volume для certbot правильно смонтирован

```bash
# Проверьте, что volume существует
docker volume ls | grep certbot

# Проверьте содержимое
docker-compose exec nginx ls -la /var/www/certbot
```

## Решение проблемы

### Шаг 1: Убедитесь, что Nginx работает на HTTP

```bash
# Перезапустите Nginx
docker-compose restart nginx

# Проверьте доступность
curl -I http://bot.usemycontent.ru/health
# Должен вернуть: HTTP/1.1 200 OK
```

### Шаг 2: Проверьте доступность извне

```bash
# С вашего компьютера или другого сервера
curl -I http://bot.usemycontent.ru/.well-known/acme-challenge/test

# Или используйте онлайн-сервис:
# https://www.yougetsignal.com/tools/open-ports/
# Проверьте, что порт 80 открыт на IP 31.59.106.143
```

### Шаг 3: Если порт закрыт в firewall

```bash
# Ubuntu/Debian
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw reload

# CentOS/RHEL
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --permanent --add-service=https
sudo firewall-cmd --reload

# Проверьте iptables
sudo iptables -L -n | grep 80
```

### Шаг 4: Если проблема в провайдере

Некоторые провайдеры блокируют входящие соединения на порты 80/443. Проверьте:
- Настройки firewall на уровне провайдера
- Настройки security group в облаке (AWS, DigitalOcean, etc.)

### Шаг 5: Повторная попытка получения сертификата

После исправления проблем:

```bash
# Убедитесь, что Nginx работает
docker-compose up -d nginx

# Проверьте доступность
curl -I http://bot.usemycontent.ru/.well-known/acme-challenge/test

# Повторите получение сертификата
cd nginx
./init-letsencrypt.sh
```

## После успешного получения сертификата

```bash
# Включите HTTPS
./enable-https.sh

# Перезагрузите Nginx
docker-compose exec nginx nginx -t  # Проверка
docker-compose exec nginx nginx -s reload
```

## Альтернативные методы получения сертификата

Если webroot метод не работает, можно использовать DNS challenge:

```bash
docker compose run --rm --entrypoint "\
  certbot certonly --manual --preferred-challenges dns \
    -d bot.usemycontent.ru \
    --email your@email.com \
    --agree-tos" certbot
```

Этот метод потребует добавления TXT записи в DNS.
