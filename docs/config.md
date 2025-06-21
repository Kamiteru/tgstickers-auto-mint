# Конфигурация

## Обязательные параметры

### 1. JWT токен Stickerdom

```env
STICKERDOM_JWT_TOKEN=your_jwt_token_here
```

**Как получить JWT токен:**

1. Откройте [stickerdom.store](https://stickerdom.store) в браузере
2. Откройте DevTools (F12) → Network
3. Авторизуйтесь на сайте
4. Найдите любой запрос к API
5. Скопируйте значение из заголовка `Authorization: Bearer xxx`

### 2. Методы оплаты

```env
PAYMENT_METHODS=TON,STARS
```

Доступные методы: `TON`, `STARS`

## Настройка TON платежей

```env
TON_SEED_PHRASE=word1 word2 word3 ... word24
TON_ENDPOINT=mainnet
```

## Настройка Telegram Stars

```env
# Получите на https://my.telegram.org
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=your_api_hash
TELEGRAM_PHONE=+1234567890
TELEGRAM_SESSION_NAME=stars_session
```

## Rate Limiter профили

```env
# Профили: safe, balanced, fast, aggressive, extreme
RATE_LIMITER_PROFILE=balanced
RATE_LIMITER_ENABLED=true
```

## Stars профили

```env
# Профили: conservative, balanced, aggressive, extreme
STARS_PROFILE=balanced
STARS_MAX_PURCHASES_PER_SESSION=3
STARS_PURCHASE_INTERVAL=2.0
```

## Уведомления

```env
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
```

## CAPTCHA решение

```env
CAPTCHA_ENABLED=true
ANTICAPTCHA_API_KEY=your_anticaptcha_key
```

## Дополнительные настройки

```env
# Прокси (опционально)
PROXY_ENABLED=false
PROXY_URL=http://user:pass@host:port

# Логирование
LOG_LEVEL=INFO
LOG_TO_FILE=true

# Тестовый режим
DRY_RUN_MODE=false
TEST_MODE=false
```

## Проверка конфигурации

```bash
# Тест всех настроек
python main.py 2/19 --test

# Тест уведомлений
python main.py 2/19 --test-notifications

# Информация о Stars сессии
python main.py 2/19 --session-info
```

## Следующий шаг

После настройки переходите к [запуску](run.md) системы. 