# 🚀 Быстрый деплой на сервер

## Подготовка сервера

### 1. Установка Docker
```bash
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER
sudo reboot
```

### 2. Установка Docker Compose
```bash
sudo curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
sudo chmod +x /usr/local/bin/docker-compose
```

## Деплой приложения

### 1. Клонирование
```bash
git clone <your-repo-url> /opt/voice-assistant
cd /opt/voice-assistant
```

### 2. Настройка .env
```bash
cp env.example .env
nano .env
```

Заполните переменные:
- `TWILIO_ACCOUNT_SID`
- `TWILIO_AUTH_TOKEN` 
- `TWILIO_PHONE_NUMBER`
- `COMPANY_NAME`
- `WEBSITE_URL=https://lisa.automatonsoft.de`

### 3. Настройка Nginx
```bash
sudo ./setup-nginx.sh
```

### 4. SSL сертификат
```bash
sudo certbot --nginx -d lisa.automatonsoft.de
```

### 5. Запуск приложения
```bash
./deploy.sh
```

### 6. Автозапуск
```bash
sudo cp voice-assistant.service /etc/systemd/system/
sudo systemctl enable voice-assistant.service
sudo systemctl start voice-assistant.service
```

## Проверка

```bash
# Статус
docker-compose ps

# Логи
docker-compose logs -f

# Тест
curl -I https://lisa.automatonsoft.de/health
```

## Обновление

```bash
cd /opt/voice-assistant
git pull
./deploy.sh
```

## Архитектура

```
Интернет → Nginx (443) → Docker Nginx (8080) → Flask (5000)
```

- **Порт 443** - HTTPS с SSL сертификатом
- **Порт 8080** - Внутренний Nginx в Docker
- **Порт 5000** - Flask приложение
