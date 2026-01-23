#!/bin/bash

# Script to generate self-signed SSL certificate for IP address or testing
# Note: Self-signed certificates will show warnings in browsers and may not work with Instagram webhooks

set -e

if [ -z "$1" ]; then
    echo "Usage: $0 <IP_ADDRESS_OR_DOMAIN>"
    echo "Example: $0 31.59.106.143"
    echo "Example: $0 webhook.example.com"
    exit 1
fi

TARGET=$1
CERT_NAME="${TARGET//./_}"

echo "=== Generating self-signed certificate for $TARGET ==="
echo ""
echo "⚠️  WARNING: Self-signed certificates:"
echo "   - Will show security warnings in browsers"
echo "   - May not work with Instagram webhooks (Instagram requires valid SSL)"
echo "   - Should only be used for testing"
echo ""
read -p "Continue? (y/N) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    exit 1
fi

# Create directory structure in Docker volume
echo "Creating certificate in Docker volume..."

# Use Docker to create certificate in the volume
docker compose run --rm --entrypoint "\
  mkdir -p /etc/letsencrypt/live/$CERT_NAME && \
  openssl req -x509 -nodes -newkey rsa:4096 \
    -days 365 \
    -keyout /etc/letsencrypt/live/$CERT_NAME/privkey.pem \
    -out /etc/letsencrypt/live/$CERT_NAME/fullchain.pem \
    -subj '/CN=$TARGET' \
    -addext 'subjectAltName=IP:$TARGET,DNS:$TARGET'" certbot

echo ""
echo "✅ Certificate generated in Docker volume:"
echo "   - Private key: /etc/letsencrypt/live/$CERT_NAME/privkey.pem"
echo "   - Certificate: /etc/letsencrypt/live/$CERT_NAME/fullchain.pem"
echo ""
echo "📝 Next steps:"
echo "1. Update nginx/nginx.conf:"
echo "   Replace YOUR_DOMAIN with $CERT_NAME:"
echo "   ssl_certificate /etc/letsencrypt/live/$CERT_NAME/fullchain.pem;"
echo "   ssl_certificate_key /etc/letsencrypt/live/$CERT_NAME/privkey.pem;"
echo ""
echo "2. Restart nginx:"
echo "   docker-compose restart nginx"
echo ""
echo "⚠️  IMPORTANT: Self-signed certificates may NOT work with Instagram webhooks!"
echo "   Instagram requires valid SSL certificates from trusted CAs."
echo "   For production, you MUST use a domain name with Let's Encrypt certificate."
echo "   See nginx/SETUP_FOR_IP.md for alternatives."
