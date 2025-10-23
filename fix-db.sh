#!/bin/bash

# Скрипт для исправления проблемы с базой данных
# Использование: ./fix-db.sh

set -e

echo "🔧 Исправляем проблему с базой данных..."

# Остановка контейнеров
echo "🛑 Останавливаем контейнеры..."
docker-compose down

# Создание папки и установка прав
echo "📁 Создаем папку и устанавливаем права..."
docker-compose run --rm --user root voice-assistant mkdir -p /home/app
docker-compose run --rm --user root voice-assistant chown -R app:app /home/app
docker-compose run --rm --user root voice-assistant chmod 755 /home/app

# Создание базы данных вручную
echo "🗄️ Создаем базу данных вручную..."
docker-compose run --rm voice-assistant python -c "
import sqlite3
conn = sqlite3.connect('/home/app/voice_assistant.db')
conn.execute('CREATE TABLE calls (id INTEGER PRIMARY KEY, call_sid TEXT, phone_number TEXT, language TEXT, status TEXT, created_at DATETIME, updated_at DATETIME)')
conn.execute('CREATE TABLE conversations (id INTEGER PRIMARY KEY, call_id INTEGER, step TEXT, user_input TEXT, bot_response TEXT, timestamp DATETIME)')
conn.execute('CREATE TABLE orders (id INTEGER PRIMARY KEY, call_id INTEGER, order_number TEXT, status TEXT, notes TEXT, created_at DATETIME, updated_at DATETIME)')
conn.close()
print('База данных создана успешно')
"

# Запуск контейнеров
echo "🚀 Запускаем контейнеры..."
docker-compose up -d

# Ожидание запуска
echo "⏳ Ожидаем запуска..."
sleep 10

# Проверка статуса
echo "📊 Проверяем статус..."
docker-compose ps

# Проверка здоровья
echo "🏥 Проверяем здоровье..."
if curl -f http://localhost:8283/health > /dev/null 2>&1; then
    echo "✅ Приложение работает!"
else
    echo "❌ Приложение не отвечает!"
    echo "📋 Логи:"
    docker-compose logs --tail=20
    exit 1
fi

echo "🎉 Проблема с базой данных исправлена!"
