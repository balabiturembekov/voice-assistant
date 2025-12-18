# Настройка транскрипции для немецкого языка

## Проблема

Twilio по умолчанию использует английский язык (en-US) для транскрипции. Встроенная транскрипция Twilio для `<Record>` **НЕ поддерживает немецкий язык** должным образом. Даже при установке `transcribeLanguage="de-DE"`, Twilio будет транскрибировать немецкую речь как английскую или с очень низкой точностью.

## Решения

### 1. Для `<Gather>` с `input="speech"` (распознавание речи в реальном времени)

✅ **ИСПРАВЛЕНО**: Код теперь использует правильный формат языка и speechModel:

```python
speech_language = "de-DE"  # Правильный формат (не просто "de")
speech_model = "googlev2_telephony"  # Google STT V2 для лучшей точности

gather = response.gather(
    input="speech",
    language=speech_language,
    speech_model=speech_model,
    ...
)
```

**Важно**: Убедитесь, что в консоли Twilio включен провайдер Google STT V2 или Deepgram Nova-3:
- Twilio Console → Settings → Speech Recognition
- Выберите "Google STT V2" или "Deepgram Nova-3"
- Эти провайдеры поддерживают de-DE

### 2. Для `<Record>` (запись голосовых сообщений)

⚠️ **ПРОБЛЕМА**: Twilio встроенная транскрипция не поддерживает немецкий.

**Решение**: Используйте внешний сервис транскрипции.

#### Вариант A: Google Cloud Speech-to-Text (Рекомендуется)

**Преимущества**:
- Отличная поддержка немецкого языка (de-DE)
- Бесплатный tier: 60 минут/месяц
- Высокая точность
- Хорошая документация

**Установка**:

1. Установите библиотеку:
```bash
pip install google-cloud-speech
```

2. Создайте проект в Google Cloud Console:
   - Перейдите на https://console.cloud.google.com/
   - Создайте новый проект или выберите существующий
   - Включите API "Cloud Speech-to-Text"

3. Создайте Service Account:
   - IAM & Admin → Service Accounts
   - Создайте новый service account
   - Скачайте JSON ключ

4. Настройте переменные окружения:
```bash
# Вариант 1: Указать путь к JSON ключу
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account-key.json

# Вариант 2: Использовать gcloud CLI
gcloud auth application-default login
```

5. Обновите `.env`:
```bash
TRANSCRIPTION_SERVICE=google
```

#### Вариант B: Deepgram API

**Преимущества**:
- Отличная поддержка немецкого
- Простая интеграция
- Хорошая точность

**Установка**:

1. Зарегистрируйтесь на https://deepgram.com/
2. Получите API ключ из https://console.deepgram.com/
3. Обновите `.env`:
```bash
TRANSCRIPTION_SERVICE=deepgram
DEEPGRAM_API_KEY=your_api_key_here
```

#### Вариант C: Twilio Add-ons (устарело)

В Twilio Marketplace есть add-ons для транскрипции (IBM Watson и др.), но они могут быть платными и устаревшими. Рекомендуется использовать кастомную интеграцию.

## Текущая реализация

Код автоматически использует внешний сервис, если он настроен:

1. В `handle_recording_status()` проверяется `Config.TRANSCRIPTION_SERVICE`
2. Если установлен `google` или `deepgram`, используется внешний сервис
3. Транскрипция сохраняется в базу данных и отправляется в email

## Тестирование

1. **Тест с Twilio (по умолчанию)**:
   ```bash
   TRANSCRIPTION_SERVICE=twilio
   ```
   - Ожидайте низкую точность для немецкого
   - Транскрипция будет на английском или искаженная

2. **Тест с Google Cloud**:
   ```bash
   TRANSCRIPTION_SERVICE=google
   export GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json
   ```
   - Ожидайте высокую точность для немецкого
   - Транскрипция будет на правильном языке

3. **Тест с Deepgram**:
   ```bash
   TRANSCRIPTION_SERVICE=deepgram
   DEEPGRAM_API_KEY=your_key
   ```
   - Ожидайте высокую точность для немецкого

## Стоимость

- **Twilio**: ~$0.006/минуту (встроенная транскрипция)
- **Google Cloud**: Бесплатно до 60 минут/месяц, затем ~$0.006/минуту
- **Deepgram**: Зависит от плана, обычно ~$0.0043/минуту

## Рекомендации

1. Для продакшена используйте **Google Cloud Speech-to-Text** или **Deepgram**
2. Для разработки можно использовать Twilio (но ожидайте низкую точность для немецкого)
3. Всегда тестируйте с реальными немецкими голосовыми сообщениями
4. Мониторьте логи для отслеживания успешности транскрипции

## Дополнительные улучшения

- Добавьте fallback: если внешний сервис недоступен, используйте Twilio
- Кэшируйте транскрипции для одинаковых аудио
- Добавьте метрики для отслеживания точности транскрипции

