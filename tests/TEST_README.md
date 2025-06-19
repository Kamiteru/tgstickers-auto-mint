# 🧪 Tests

Тестовый набор для проекта TG Stickers Auto-Mint.

## Структура

```
tests/
├── __init__.py              # Python package initialization
├── README.md                # Эта документация
├── run_all_tests.py         # Запуск всех тестов
├── test_api.py              # Тесты API подключения
├── test_captcha.py          # Тесты системы captcha
└── test_wallet.py           # Тесты TON кошелька
```

## Быстрый запуск

### Все тесты (из корня проекта)
```bash
python run_tests.py
```

### Отдельные тесты
```bash
# API тесты
python tests/test_api.py

# Captcha тесты
python tests/test_captcha.py

# Wallet тесты  
python tests/test_wallet.py

# Все тесты напрямую
python tests/run_all_tests.py
```

## Покрытие тестами

✅ **API Connection Tests (3/3)**
- Подключение к API
- Получение коллекций
- Получение цен

✅ **Captcha System Tests (3/3)**  
- Обнаружение captcha
- Ручное решение
- Интеграция с сервисами

✅ **TON Wallet Tests (4/4)**
- Подключение кошелька
- Получение баланса
- Проверка адреса
- Dry run транзакций

✅ **Main.py Tests (2/2)**
- Тестовый режим
- Тесты уведомлений

✅ **Import Tests (1/1)**
- Проверка всех критических импортов

## Результат тестов

При успешном прохождении всех тестов вы увидите:
```
🎉 ALL TESTS PASSED! Project is ready to use.
```

## Требования

Все тесты требуют правильно настроенный `.env` файл с:
- `STICKERDOM_JWT_TOKEN`
- `TON_SEED_PHRASE` 
- `TELEGRAM_BOT_TOKEN` (для тестов уведомлений)
- `TELEGRAM_CHAT_ID` (для тестов уведомлений) 