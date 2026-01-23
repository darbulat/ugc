#!/bin/bash

# Скрипт для быстрой настройки SSL для Instagram webhook

set -e

echo "=== Настройка HTTPS для Instagram Webhook ==="
echo ""

# Проверка наличия docker compose
if ! command -v docker &> /dev/null; then
    echo "❌ Docker не установлен. Установите Docker и повторите попытку."
    exit 1
fi

# Запрос домена
read -p "Введите ваш домен (например, webhook.example.com): " DOMAIN
if [ -z "$DOMAIN" ]; then
    echo "❌ Домен не может быть пустым"
    exit 1
fi

# Запрос email
read -p "Введите ваш email для Let's Encrypt (рекомендуется): " EMAIL
if [ -z "$EMAIL" ]; then
    EMAIL=""
    echo "⚠️  Email не указан, будет использован режим без email"
fi

# Обновление nginx.conf
echo "📝 Обновление nginx.conf..."
sed -i.bak "s/YOUR_DOMAIN/$DOMAIN/g" nginx.conf
rm -f nginx.conf.bak

# Обновление init-letsencrypt.sh
echo "📝 Обновление init-letsencrypt.sh..."
sed -i.bak "s/YOUR_DOMAIN/$DOMAIN/g" init-letsencrypt.sh
if [ -n "$EMAIL" ]; then
    sed -i.bak "s/YOUR_EMAIL/$EMAIL/g" init-letsencrypt.sh
else
    sed -i.bak "s/YOUR_EMAIL/\"\"/g" init-letsencrypt.sh
fi
rm -f init-letsencrypt.sh.bak

echo ""
echo "✅ Конфигурация обновлена!"
echo ""
echo "Следующие шаги:"
echo "1. Убедитесь, что домен $DOMAIN указывает на IP этого сервера (A-запись)"
echo "2. Убедитесь, что порты 80 и 443 открыты в firewall"
echo "3. Запустите: ./nginx/init-letsencrypt.sh"
echo "4. После получения сертификата запустите: docker-compose up -d"
echo ""
echo "Webhook будет доступен по адресу: https://$DOMAIN/webhook/instagram"
