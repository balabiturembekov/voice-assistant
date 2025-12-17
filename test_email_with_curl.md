# Тестирование отправки email через curl

## Предварительные требования

1. Flask сервер должен быть запущен (по умолчанию на порту 5001)
2. Email настройки должны быть в `.env` файле:
   ```env
   MAIL_SERVER=smtp.gmail.com
   MAIL_PORT=587
   MAIL_USE_TLS=True
   MAIL_USERNAME=your_email@gmail.com
   MAIL_PASSWORD=your_app_password
   MAIL_RECIPIENT=recipient@example.com
   ```
3. База данных должна быть инициализирована

## Быстрый тест (автоматизированный скрипт)

```bash
# Запустите автоматизированный тест
./test_email_curl.sh http://localhost:5001
```

## Ручные curl команды

### 1. Тест записи голосового сообщения (немецкий)

```bash
# Шаг 1: Создать запись звонка
CALL_SID="TEST_CALL_DE_$(date +%s)"
curl -X POST "http://localhost:5001/webhook/voice" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "CallSid=$CALL_SID" \
  -d "From=%2B491234567890"

# Шаг 2: Отправить запись
curl -X POST "http://localhost:5001/webhook/recorded" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "CallSid=$CALL_SID" \
  -d "From=%2B491234567890" \
  -d "RecordingUrl=https://api.twilio.com/2010-04-01/Accounts/ACxxx/Recordings/REtest123" \
  -d "RecordingSid=REtest123" \
  -d "RecordingDuration=25" \
  -d "RecordingStatus=completed" \
  -d "RecordingTranscription=Dies ist eine Testnachricht auf Deutsch. Bitte antworten Sie auf diese E-Mail." \
  -d "Digits=%23"
```

### 2. Тест записи голосового сообщения (английский)

```bash
# Шаг 1: Создать запись звонка
CALL_SID="TEST_CALL_EN_$(date +%s)"
curl -X POST "http://localhost:5001/webhook/voice" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "CallSid=$CALL_SID" \
  -d "From=%2B1234567890"

# Шаг 2: Отправить запись
curl -X POST "http://localhost:5001/webhook/recorded" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "CallSid=$CALL_SID" \
  -d "From=%2B1234567890" \
  -d "RecordingUrl=https://api.twilio.com/2010-04-01/Accounts/ACxxx/Recordings/REtest456" \
  -d "RecordingSid=REtest456" \
  -d "RecordingDuration=30" \
  -d "RecordingStatus=completed" \
  -d "RecordingTranscription=This is a test message in English. Please reply to this email." \
  -d "Digits=%23"
```

### 3. Тест callback транскрипции (обновление email)

```bash
# Шаг 1: Создать запись звонка
CALL_SID="TEST_CALL_TRANS_$(date +%s)"
curl -X POST "http://localhost:5001/webhook/voice" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "CallSid=$CALL_SID" \
  -d "From=%2B491234567890"

# Шаг 2: Отправить запись (без транскрипции)
curl -X POST "http://localhost:5001/webhook/recorded" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "CallSid=$CALL_SID" \
  -d "From=%2B491234567890" \
  -d "RecordingUrl=https://api.twilio.com/2010-04-01/Accounts/ACxxx/Recordings/REtrans123" \
  -d "RecordingSid=REtrans123" \
  -d "RecordingDuration=20" \
  -d "RecordingStatus=completed" \
  -d "RecordingTranscription=" \
  -d "Digits=%23"

# Шаг 3: Отправить транскрипцию (обновит email)
curl -X POST "http://localhost:5001/webhook/transcription" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "CallSid=$CALL_SID" \
  -d "RecordingSid=REtrans123" \
  -d "TranscriptionText=Dies ist die vollständige Transkription der Sprachnachricht. Sie wurde erfolgreich verarbeitet." \
  -d "TranscriptionStatus=completed"
```

## Что проверять после тестов

1. **Проверьте email inbox** - должны прийти письма с:
   - Номером звонящего
   - Ссылкой на запись
   - Транскрипцией сообщения
   - Длительностью записи
   - Номером заказа (если доступен)

2. **Проверьте логи Flask** - не должно быть ошибок отправки email

3. **Проверьте базу данных** - записи должны быть созданы в таблицах `calls` и `conversations`

## Примечания

- Порт по умолчанию: **5001** (если Flask запущен локально)
- Для продакшена используйте ваш публичный URL (например, через ngrok или домен)
- `%2B` в curl - это URL-encoded `+` для номеров телефонов
- `%23` в curl - это URL-encoded `#` (символ завершения записи)

