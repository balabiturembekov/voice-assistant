#!/bin/bash

# Скрипт для настройки основного Nginx на сервере
# Использование: sudo ./setup-nginx.sh

set -e

DOMAIN="lisa.automatonsoft.de"
NGINX_CONFIG="/etc/nginx/sites-available/$DOMAIN"
NGINX_ENABLED="/etc/nginx/sites-enabled/$DOMAIN"

echo "🔧 Настраиваем Nginx для домена $DOMAIN..."

# Создание конфигурации Nginx
echo "📝 Создаем конфигурацию Nginx..."
cat > $NGINX_CONFIG << EOF
server {
    listen 80;
    server_name $DOMAIN;
    
    # Redirect HTTP to HTTPS
    return 301 https://\$server_name\$request_uri;
}

server {
    listen 443 ssl http2;
    server_name $DOMAIN;
    
    # SSL сертификаты (будут настроены позже)
    # ssl_certificate /etc/letsencrypt/live/$DOMAIN/fullchain.pem;
    # ssl_certificate_key /etc/letsencrypt/live/$DOMAIN/privkey.pem;
    
    # SSL настройки
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-RSA-AES256-GCM-SHA512:DHE-RSA-AES256-GCM-SHA512:ECDHE-RSA-AES256-GCM-SHA384:DHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;
    
    # HSTS
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    
    # Проксирование на внутренний Nginx
    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        
        # Timeouts
        proxy_connect_timeout 30s;
        proxy_send_timeout 30s;
        proxy_read_timeout 30s;
    }
}
EOF

# Активация конфигурации
echo "🔗 Активируем конфигурацию..."
ln -sf $NGINX_CONFIG $NGINX_ENABLED

# Проверка конфигурации
echo "✅ Проверяем конфигурацию Nginx..."
nginx -t

# Перезагрузка Nginx
echo "🔄 Перезагружаем Nginx..."
systemctl reload nginx

echo "🎉 Nginx настроен успешно!"
echo ""
echo "📋 Следующие шаги:"
echo "1. Настройте DNS для домена $DOMAIN"
echo "2. Получите SSL сертификат:"
echo "   sudo certbot --nginx -d $DOMAIN"
echo "3. Запустите приложение:"
echo "   ./deploy.sh"
