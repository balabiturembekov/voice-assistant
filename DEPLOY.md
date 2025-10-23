# Деплой Voice Assistant на сервер

## Подготовка сервера

### 1. Установка Docker и Docker Compose
```bash
# Обновление системы
sudo apt update && sudo apt upgrade -y

# Установка Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER

# Установка Docker Compose
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose

# Перезагрузка для применения изменений
sudo reboot
```

### 2. Настройка основного Nginx (на сервере)

Создайте файл `/etc/nginx/sites-available/lisa.automatonsoft.de`:

```nginx
server {
    listen 80;
    server_name lisa.automatonsoft.de;
    
    # Redirect HTTP to HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name lisa.automatonsoft.de;
    
    # SSL сертификаты (замените на ваши)
    ssl_certificate /etc/letsencrypt/live/lisa.automatonsoft.de/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/lisa.automatonsoft.de/privkey.pem;
    
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
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # Timeouts
        proxy_connect_timeout 30s;
        proxy_send_timeout 30s;
        proxy_read_timeout 30s;
    }
}
```

Активируйте конфигурацию:
```bash
sudo ln -s /etc/nginx/sites-available/lisa.automatonsoft.de /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### 3. Получение SSL сертификата

```bash
# Установка Certbot
sudo apt install certbot python3-certbot-nginx

# Получение сертификата
sudo certbot --nginx -d lisa.automatonsoft.de
```

## Деплой приложения

### 1. Клонирование репозитория
```bash
git clone <your-repo-url> /opt/voice-assistant
cd /opt/voice-assistant
```

### 2. Создание .env файла
```bash
cp env.example .env
nano .env
```

Заполните переменные:
```env
# Twilio Credentials
TWILIO_ACCOUNT_SID=your_account_sid_here
TWILIO_AUTH_TOKEN=your_auth_token_here
TWILIO_PHONE_NUMBER=your_twilio_phone_number_here

# Company Information
COMPANY_NAME=Your Company Name
WEBSITE_URL=https://lisa.automatonsoft.de

# Voice Configuration
VOICE_NAME=alice

# Database Configuration
DATABASE_URL=sqlite:////home/app/voice_assistant.db

# Flask Configuration
FLASK_ENV=production
FLASK_DEBUG=False
```

### 3. Запуск приложения
```bash
# Сборка и запуск
docker-compose up -d --build

# Проверка статуса
docker-compose ps

# Просмотр логов
docker-compose logs -f
```

### 4. Настройка автозапуска

Создайте systemd сервис `/etc/systemd/system/voice-assistant.service`:

```ini
[Unit]
Description=Voice Assistant Docker Compose
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/voice-assistant
ExecStart=/usr/local/bin/docker-compose up -d
ExecStop=/usr/local/bin/docker-compose down
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
```

Активируйте сервис:
```bash
sudo systemctl enable voice-assistant.service
sudo systemctl start voice-assistant.service
```

## Мониторинг

### Просмотр логов
```bash
# Логи приложения
docker-compose logs -f voice-assistant

# Логи Nginx
docker-compose logs -f nginx

# Системные логи
sudo journalctl -u voice-assistant.service -f
```

### Проверка статуса
```bash
# Статус контейнеров
docker-compose ps

# Статус сервиса
sudo systemctl status voice-assistant.service

# Проверка доступности
curl -I https://lisa.automatonsoft.de/health
```

## Обновление приложения

```bash
cd /opt/voice-assistant

# Остановка
docker-compose down

# Обновление кода
git pull

# Пересборка и запуск
docker-compose up -d --build
```

## Резервное копирование

```bash
# Создание бэкапа базы данных
docker-compose exec voice-assistant cp /home/app/voice_assistant.db /tmp/backup_$(date +%Y%m%d_%H%M%S).db

# Восстановление из бэкапа
docker-compose exec voice-assistant cp /tmp/backup_YYYYMMDD_HHMMSS.db /home/app/voice_assistant.db
```

## Безопасность

1. **Firewall**: Настройте UFW для открытия только необходимых портов
2. **SSL**: Используйте Let's Encrypt для автоматического обновления сертификатов
3. **Обновления**: Регулярно обновляйте систему и Docker образы
4. **Мониторинг**: Настройте мониторинг доступности сервиса

## Troubleshooting

### Проблемы с базой данных
```bash
# Проверка подключения к БД
docker-compose exec voice-assistant python -c "from app import app, db; app.app_context().push(); print('DB OK')"

# Пересоздание БД
docker-compose exec voice-assistant python init_db.py
```

### Проблемы с Nginx
```bash
# Проверка конфигурации
sudo nginx -t

# Перезагрузка Nginx
sudo systemctl reload nginx
```

### Проблемы с Docker
```bash
# Очистка Docker
docker system prune -a

# Перезапуск сервисов
sudo systemctl restart voice-assistant.service
```
