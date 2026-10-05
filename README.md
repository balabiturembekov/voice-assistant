# Voice Assistant "Liza" with Twilio

Голосовой ассистент Liza с поддержкой многоязычности, GDPR согласия и веб-интерфейса для управления заказами, построенный на Twilio и Flask.

## 🎯 Основные возможности

- 🗣️ **Голосовой ассистент Liza** - персональный помощник для клиентов
- 🌍 **Многоязычность** - автоматическое определение языка по номеру телефона
- 📋 **GDPR согласие** - запрос согласия на обработку данных через DTMF (цифры 1/2)
- 📦 **Управление заказами** - ввод номера заказа через клавиатуру телефона
- ✅ **Подтверждение заказа** - повторение номера заказа для подтверждения
- 🗄️ **База данных** - сохранение всех звонков, разговоров и заказов
- 🌐 **Веб-интерфейс** - управление звонками и заказами через браузер
- 📊 **Статистика** - просмотр статистики звонков и заказов

## 🚀 Быстрый старт

### 1. Установка зависимостей

```bash
# Клонируйте репозиторий
git clone <repository-url>
cd voice-assistant

# Создайте виртуальное окружение
python -m venv venv
source venv/bin/activate  # На Windows: venv\Scripts\activate

# Установите зависимости
pip install -r requirements.txt
```

### 2. Настройка окружения

Создайте файл `.env` с вашими данными:

```bash
# Twilio Credentials
TWILIO_ACCOUNT_SID=your_account_sid_here
TWILIO_AUTH_TOKEN=your_auth_token_here
TWILIO_PHONE_NUMBER=your_twilio_phone_number_here

# Company Information
COMPANY_NAME=Your Company Name
WEBSITE_URL=https://your-website.com

# Voice Configuration
VOICE_NAME=alice  # или polly.Joanna, polly.Emma и др.

# Flask Configuration
FLASK_ENV=development
FLASK_DEBUG=True

# Database Configuration
DATABASE_URL=sqlite:///instance/voice_assistant.db
```

### 3. Инициализация базы данных

```bash
python init_db.py
```

### 4. Запуск приложения

```bash
python app.py
```

## 🏗️ Инфраструктура

`docker compose up -d --build` поднимает четыре контейнера:

| Сервис | Назначение |
|---|---|
| `voice-assistant` | Flask + gunicorn, вебхуки Twilio и дашборд (127.0.0.1:8283) |
| `worker` | RQ-воркер: письма о голосовых сообщениях, внешняя транскрипция, отложенные задачи |
| `postgres` | PostgreSQL 16, данные в volume `pgdata` |
| `redis` | очередь задач, кэш Afterbuy, лимит попыток входа |

**Схема БД** управляется миграциями Alembic: контейнер при старте выполняет
`flask --app app db upgrade`. Новая миграция после изменения моделей:
`flask --app app db migrate -m "описание"`.

**Голосовые сообщения.** Колбэки Twilio (`/webhook/recorded`, `/recording_status`,
`/transcription`) только сохраняют данные в таблицу `voice_messages` и ставят задачу
в очередь. Письмо отправляет воркер, ровно одно на `RecordingSid`, с повторами при
ошибке SMTP. Если транскрипция не пришла за `VOICE_EMAIL_FALLBACK_DELAY` секунд
(по умолчанию 300), письмо уходит без неё. Статус письма виден на странице звонка.

**Эксплуатация:**
- `./deploy.sh`: git pull, бэкап, сборка, проверка `/health`.
- `scripts/backup_db.sh`: дамп Postgres в `./backups` (хранится 14 дней).
- `scripts/crontab.example`: ночной бэкап, повтор неотправленных писем, GDPR-очистка.
- `flask --app app purge-old-data --days 90`: обезличивание старых звонков.
- `/health` проверяет базу и Redis (503, если что-то недоступно).

## 🔐 Безопасность

- **Секреты только из окружения.** Обязательные переменные: `SECRET_KEY`, `TWILIO_AUTH_TOKEN`,
  `AFTERBUY_PARTNER_ID`, `AFTERBUY_PARTNER_TOKEN`, `AFTERBUY_ACCOUNT_TOKEN`, `AFTERBUY_USER_ID`,
  `AFTERBUY_USER_PASSWORD`. Без них приложение не стартует (кроме `FLASK_DEBUG=True`).
- **Вебхуки Twilio** (`/webhook/*`) принимаются только с валидной подписью `X-Twilio-Signature`.
  Локально проверку можно выключить: `TWILIO_VALIDATE_REQUESTS=False`.
- **Дашборд и `/api/*`** доступны только после входа. Роли: `admin` (плюс управление
  пользователями на `/users`) и `operator`. Все формы и запросы защищены CSRF-токеном.
- **Логи** не содержат текстов транскрипций, номера телефонов маскируются (`***678`).

Первый администратор создаётся из CLI:

```bash
flask --app app create-user admin --role admin
# в Docker:
docker compose exec voice-assistant flask --app app create-user admin --role admin
```

Проверка отправки email: `flask --app app send-test-email`.

Тесты: `pip install -r requirements-dev.txt && pytest`.

## 📞 Настройка Twilio

1. Войдите в [Twilio Console](https://console.twilio.com/)
2. Перейдите в Phone Numbers → Manage → Active numbers
3. Выберите ваш номер телефона
4. В разделе "Voice" установите:
   - **Webhook URL**: `https://your-domain.com/webhook/voice`
   - **HTTP Method**: POST

## 🎯 Логика работы

### 1. Входящий звонок
- Liza приветствует клиента на соответствующем языке
- Представляется как "Liza, ваш голосовой ассистент"

### 2. GDPR согласие
- Запрашивает согласие на обработку данных
- **Клиент нажимает**: 1 (Да) или 2 (Нет)
- При отказе - завершает звонок

### 3. Ввод номера заказа
- Просит ввести номер заказа через клавиатуру телефона
- **Клиент вводит**: номер заказа и нажимает #
- Валидирует номер заказа

### 4. Подтверждение заказа
- Повторяет введенный номер заказа (каждая цифра отдельно)
- **Клиент нажимает**: 1 (Да) или 2 (Нет)
- При подтверждении - сохраняет заказ в базу данных

### 5. Статус заказа
- Сообщает статус заказа
- Предлагает дополнительную помощь

## 🌍 Поддерживаемые языки

- **🇩🇪 Немецкий** - по умолчанию для всех номеров
- **🇺🇸 Английский** - для номеров США/Великобритании (+1, +44)

## 🗄️ База данных

### Модели данных

- **Call** - информация о звонке (номер, язык, статус)
- **Conversation** - диалог с клиентом (шаги, ответы)
- **Order** - заказы клиентов (номер, статус, заметки)

### Статусы звонков

- **В обработке** - новый звонок
- **Обработано** - получено согласие
- **Завершен** - звонок завершен
- **Проблема** - возникла проблема

## 🌐 Веб-интерфейс

### Доступные страницы

- **`/`** - Главная страница с информацией
- **`/calls`** - Список всех звонков с фильтрацией
- **`/calls/<id>`** - Детали конкретного звонка
- **`/orders`** - Список всех заказов
- **`/orders/<id>`** - Детали конкретного заказа

### Функции веб-интерфейса

- 📊 **Пагинация** - просмотр больших списков
- 🔍 **Фильтрация** - поиск по статусу, дате, номеру
- ✏️ **Редактирование** - изменение статусов звонков и заказов
- 📱 **Адаптивный дизайн** - работает на всех устройствах

## 🔧 API Endpoints

### Webhook endpoints
- `POST /webhook/voice` - Входящие звонки
- `POST /webhook/consent` - Обработка согласия (DTMF)
- `POST /webhook/order` - Ввод номера заказа (DTMF)
- `POST /webhook/order_confirm` - Подтверждение заказа (DTMF)
- `POST /webhook/help` - Дополнительная помощь

### Web endpoints
- `GET /` - Главная страница
- `GET /calls` - Список звонков
- `GET /calls/<id>` - Детали звонка
- `GET /orders` - Список заказов
- `GET /orders/<id>` - Детали заказа

### API endpoints
- `POST /api/calls/<id>/status` - Изменение статуса звонка
- `POST /api/orders/<id>/status` - Изменение статуса заказа
- `GET /health` - Проверка состояния
- `GET /api/health` - API health check

## 🎛️ Конфигурация

### Голоса Twilio

```python
# Стандартные голоса
VOICE_NAME=alice
VOICE_NAME=man
VOICE_NAME=woman

# Amazon Polly голоса (премиум)
VOICE_NAME=polly.Joanna
VOICE_NAME=polly.Emma
VOICE_NAME=polly.Amy
VOICE_NAME=polly.Kimberly
```

### Настройка компании

```python
COMPANY_NAME=Your Company Name
WEBSITE_URL=https://your-website.com
```

## 🚀 Развертывание

### Локальная разработка

```bash
python app.py
```

### Продакшн с Gunicorn

```bash
gunicorn -w 4 -b 0.0.0.0:5000 app:app
```

### Docker

```bash
# Сборка образа
docker build -t voice-assistant .

# Запуск контейнера
docker run -p 5000:5000 voice-assistant
```

### Docker Compose

```bash
# With Nginx (recommended for production)
docker-compose up -d

# Or use the convenience script
./start-with-nginx.sh
```

### Docker Compose Services

- **voice-assistant** - Flask приложение
- **nginx** - Reverse proxy и статические файлы
- **voice-assistant-network** - Внутренняя сеть Docker

### Nginx Configuration

Nginx настроен как reverse proxy с:

- **Rate Limiting** - защита от DDoS атак
- **Static Files** - обслуживание CSS/JS файлов
- **Security Headers** - защита от XSS и других атак
- **Gzip Compression** - сжатие для ускорения
- **Health Checks** - мониторинг состояния

#### Порты:
- **80** - HTTP (основной)
- **443** - HTTPS (настроить SSL сертификаты)
- **5000** - Прямой доступ к Flask (только для разработки)

## 📊 Мониторинг и логирование

### Логирование

- Все звонки логируются в базу данных
- Сохраняются все диалоги с клиентами
- Отслеживаются статусы звонков и заказов

### Метрики

- Количество звонков по дням/неделям
- Статистика согласий/отказов
- Популярные номера заказов
- Время обработки звонков

## 🔒 Безопасность

- **HTTPS** - все данные передаются через защищенное соединение
- **GDPR** - полная совместимость с европейским законодательством
- **Валидация** - проверка всех входящих данных
- **Логирование** - аудит всех действий

## 🛠️ Разработка

### Структура проекта

```
voice-assistant/
├── app.py                 # Основное приложение
├── config.py             # Конфигурация
├── models.py             # Модели базы данных
├── init_db.py            # Инициализация БД
├── migrate_db.py         # Миграции БД
├── view_calls.py         # Просмотр звонков
├── requirements.txt      # Зависимости
├── docker-compose.yml    # Docker конфигурация
├── templates/            # HTML шаблоны
│   ├── base.html
│   ├── calls.html
│   ├── orders.html
│   └── ...
└── static/               # Статические файлы
    ├── css/
    └── js/
```

### Добавление новых функций

1. Создайте новый webhook endpoint в `app.py`
2. Добавьте соответствующий TwiML response
3. Обновите модели базы данных при необходимости
4. Добавьте веб-интерфейс в `templates/`

## 📞 Тестирование

### Локальное тестирование

```bash
# Запуск приложения
python app.py

# Тестирование webhook
curl -X POST http://localhost:5000/webhook/voice \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "From=%2B4973929378420&CallSid=test_call"
```

### Тестирование с ngrok

```bash
# Установите ngrok
npm install -g ngrok

# Запустите туннель
ngrok http 5000

# Используйте URL ngrok в настройках Twilio
```

## 🚀 Деплой на сервер

### Подготовка сервера

1. **Установка Docker и Docker Compose:**
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
   ```

2. **Клонирование и настройка:**
   ```bash
   git clone <your-repo-url> /opt/voice-assistant
   cd /opt/voice-assistant
   
   # Настройка .env файла
   cp env.example .env
   nano .env
   ```

3. **Настройка основного Nginx:**
   ```bash
   sudo ./setup-nginx.sh
   ```

4. **Получение SSL сертификата:**
   ```bash
   sudo certbot --nginx -d lisa.automatonsoft.de
   ```

5. **Запуск приложения:**
   ```bash
   ./deploy.sh
   ```

6. **Настройка автозапуска:**
   ```bash
   sudo cp voice-assistant.service /etc/systemd/system/
   sudo systemctl enable voice-assistant.service
   sudo systemctl start voice-assistant.service
   ```

### Архитектура на сервере

```
Интернет → Основной Nginx (443/80) → Внутренний Nginx (8081) → Flask App (5000)
```

- **Основной Nginx** - SSL терминация, проксирование на порт 8081
- **Внутренний Nginx** - reverse proxy для Flask приложения
- **Flask App** - основное приложение с базой данных

### Мониторинг

```bash
# Статус контейнеров
docker-compose ps

# Логи приложения
docker-compose logs -f voice-assistant

# Логи Nginx
docker-compose logs -f nginx

# Системные логи
sudo journalctl -u voice-assistant.service -f
```

## 🤝 Поддержка

Для вопросов и поддержки:

1. Проверьте логи приложения
2. Убедитесь в правильности настроек Twilio
3. Проверьте подключение к базе данных
4. Создайте issue в репозитории

## 📄 Лицензия

Этот проект распространяется под лицензией MIT. См. файл LICENSE для подробностей.

---

**Создано с ❤️ для автоматизации телефонных звонков**