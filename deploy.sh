#!/bin/bash
# Деплой на сервере: ./deploy.sh (из папки проекта)
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f .env ]; then
    echo "❌ Нет .env — скопируйте env.example и заполните" >&2
    exit 1
fi

echo "📥 git pull"
git pull --ff-only

echo "💾 Бэкап базы перед обновлением"
./scripts/backup_db.sh || echo "⚠️  Бэкап не сделан (первый запуск?)"

echo "🔨 Сборка и запуск"
docker compose up -d --build

echo "⏳ Проверка здоровья"
for i in $(seq 1 30); do
    if curl -fs http://127.0.0.1:8283/health > /dev/null; then
        curl -s http://127.0.0.1:8283/health; echo
        echo "✅ Готово"
        exit 0
    fi
    sleep 2
done
echo "❌ Приложение не ответило" >&2
docker compose logs --tail=40 voice-assistant worker >&2
exit 1
