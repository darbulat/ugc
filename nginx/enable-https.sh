#!/bin/bash

# Script to enable HTTPS after SSL certificate is obtained
# Run this after init-letsencrypt.sh completes successfully

set -e

DOMAIN="bot.usemycontent.ru"

if [ ! -f "nginx/nginx.conf" ]; then
    echo "Error: nginx/nginx.conf not found"
    exit 1
fi

echo "=== Enabling HTTPS in nginx.conf ==="
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

# Backup original config
cp nginx/nginx.conf nginx/nginx.conf.backup
echo "✅ Backup created: nginx/nginx.conf.backup"

# Enable HTTPS redirect in HTTP block
sed -i 's|#     return 301 https://$host$request_uri;|        return 301 https://$host$request_uri;|' nginx/nginx.conf
sed -i 's|# }|    }|' nginx/nginx.conf

# Uncomment HTTPS server block
sed -i "s|#     ssl_certificate /etc/letsencrypt/live/bot.usemycontent.ru/fullchain.pem;|        ssl_certificate /etc/letsencrypt/live/$DOMAIN/fullchain.pem;|" nginx/nginx.conf
sed -i "s|#     ssl_certificate_key /etc/letsencrypt/live/bot.usemycontent.ru/privkey.pem;|        ssl_certificate_key /etc/letsencrypt/live/$DOMAIN/privkey.pem;|" nginx/nginx.conf
sed -i 's|#     listen 443 ssl http2;|        listen 443 ssl http2;|' nginx/nginx.conf
sed -i 's|#     server_name _;|        server_name _;|' nginx/nginx.conf
sed -i 's|#     # SSL configuration|        # SSL configuration|' nginx/nginx.conf
sed -i 's|#     ssl_protocols|        ssl_protocols|' nginx/nginx.conf
sed -i 's|#     ssl_ciphers|        ssl_ciphers|' nginx/nginx.conf
sed -i 's|#     ssl_prefer_server_ciphers|        ssl_prefer_server_ciphers|' nginx/nginx.conf
sed -i 's|#     ssl_session_cache|        ssl_session_cache|' nginx/nginx.conf
sed -i 's|#     ssl_session_timeout|        ssl_session_timeout|' nginx/nginx.conf
sed -i 's|#     # Security headers|        # Security headers|' nginx/nginx.conf
sed -i 's|#     add_header|        add_header|' nginx/nginx.conf
sed -i 's|#     # Instagram webhook endpoint|        # Instagram webhook endpoint|' nginx/nginx.conf
sed -i 's|#     location /webhook/instagram|        location /webhook/instagram|' nginx/nginx.conf
sed -i 's|#         proxy_pass|            proxy_pass|' nginx/nginx.conf
sed -i 's|#         proxy_set_header|            proxy_set_header|' nginx/nginx.conf
sed -i 's|#         # Increase timeouts|            # Increase timeouts|' nginx/nginx.conf
sed -i 's|#         proxy_connect_timeout|            proxy_connect_timeout|' nginx/nginx.conf
sed -i 's|#         proxy_send_timeout|            proxy_send_timeout|' nginx/nginx.conf
sed -i 's|#         proxy_read_timeout|            proxy_read_timeout|' nginx/nginx.conf
sed -i 's|#         # Allow large request bodies|            # Allow large request bodies|' nginx/nginx.conf
sed -i 's|#         client_max_body_size|            client_max_body_size|' nginx/nginx.conf
sed -i 's|#     # Health check endpoint|        # Health check endpoint|' nginx/nginx.conf
sed -i 's|#     location /health|        location /health|' nginx/nginx.conf
sed -i 's|#         access_log|            access_log|' nginx/nginx.conf
sed -i 's|#         return|            return|' nginx/nginx.conf
sed -i 's|#         add_header|            add_header|' nginx/nginx.conf
sed -i 's|#     }|    }|' nginx/nginx.conf

# Remove comment markers from server block
sed -i 's|# server {|    server {|' nginx/nginx.conf

echo "✅ HTTPS enabled in nginx.conf"
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
