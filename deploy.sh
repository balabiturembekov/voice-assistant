#!/bin/bash

# Скрипт для деплоя Voice Assistant на сервер
# Использование: ./deploy.sh

set -e

echo "🚀 Начинаем деплой Voice Assistant..."

# Проверка наличия .env файла
if [ ! -f .env ]; then
    echo "❌ Файл .env не найден!"
    echo "📝 Скопируйте env.example в .env и заполните переменные:"
    echo "   cp env.example .env"
    echo "   nano .env"
    exit 1
fi

# Проверка настроек продакшена
echo "🔍 Проверяем настройки продакшена..."
if grep -q "FLASK_ENV=production" .env && grep -q "FLASK_DEBUG=False" .env; then
    echo "✅ Настройки продакшена корректны"
else
    echo "⚠️  Внимание: Убедитесь что в .env файле:"
    echo "   FLASK_ENV=production"
    echo "   FLASK_DEBUG=False"
fi

# Проверка Docker
if ! command -v docker &> /dev/null; then
    echo "❌ Docker не установлен!"
    exit 1
fi

if ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose не установлен!"
    exit 1
fi

# Остановка существующих контейнеров
echo "🛑 Останавливаем существующие контейнеры..."
docker-compose down

# Сборка образов
echo "🔨 Собираем Docker образы..."
docker-compose build --no-cache

# Запуск сервисов
echo "🚀 Запускаем сервисы..."
docker-compose up -d

# Ожидание запуска
echo "⏳ Ожидаем запуска сервисов..."
sleep 10

# Проверка статуса
echo "📊 Проверяем статус контейнеров..."
docker-compose ps

# Проверка здоровья
echo "🏥 Проверяем здоровье приложения..."
if curl -f http://localhost:8283/health > /dev/null 2>&1; then
    echo "✅ Приложение работает!"
else
    echo "❌ Приложение не отвечает!"
    echo "📋 Логи:"
    docker-compose logs --tail=20
    exit 1
fi

# Инициализация базы данных
echo "🗄️ Инициализируем базу данных..."
docker-compose exec voice-assistant python init_db.py

echo "🎉 Деплой завершен успешно!"
echo ""
echo "📋 Полезные команды:"
echo "   docker-compose ps                    # Статус контейнеров"
echo "   docker-compose logs -f               # Просмотр логов"
echo "   docker-compose restart               # Перезапуск"
echo "   docker-compose down                  # Остановка"
echo ""
echo "🌐 Приложение доступно по адресу:"
echo "   http://localhost:8283                # Локально"
echo "   https://lisa.automatonsoft.de        # Через основной Nginx"
