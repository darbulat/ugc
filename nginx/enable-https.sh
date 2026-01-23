#!/bin/bash

# Script to enable HTTPS after SSL certificate is obtained
# Run this after init-letsencrypt.sh completes successfully

set -e

DOMAIN="bot.usemycontent.ru"

if [ ! -f "nginx/nginx.conf" ]; then
    echo "Error: nginx/nginx.conf not found"
    exit 1
fi

if [ ! -f "nginx/nginx-https.conf" ]; then
    echo "Error: nginx/nginx-https.conf not found"
    exit 1
fi

echo "=== Enabling HTTPS ==="
echo ""

# Check if certificate exists
if ! docker compose exec nginx test -f "/etc/letsencrypt/live/$DOMAIN/fullchain.pem" 2>/dev/null; then
    echo "⚠️  Warning: SSL certificate not found at /etc/letsencrypt/live/$DOMAIN/fullchain.pem"
    echo "   Make sure init-letsencrypt.sh completed successfully"
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Update domain in HTTPS config if needed
if [ "$DOMAIN" != "bot.usemycontent.ru" ]; then
    echo "Updating domain in nginx-https.conf..."
    sed -i "s|bot.usemycontent.ru|$DOMAIN|g" nginx/nginx-https.conf
fi

# Backup original config
cp nginx/nginx.conf nginx/nginx.conf.backup
echo "✅ Backup created: nginx/nginx.conf.backup"

# Replace HTTP config with HTTPS config
cp nginx/nginx-https.conf nginx/nginx.conf
echo "✅ HTTPS configuration enabled"

echo ""
echo "📝 Next steps:"
echo "1. Test nginx configuration:"
echo "   docker-compose exec nginx nginx -t"
echo ""
echo "2. Reload nginx:"
echo "   docker-compose exec nginx nginx -s reload"
echo ""
echo "3. Or restart nginx:"
echo "   docker-compose restart nginx"
echo ""
echo "⚠️  If something goes wrong, restore backup:"
echo "   cp nginx/nginx.conf.backup nginx/nginx.conf"
