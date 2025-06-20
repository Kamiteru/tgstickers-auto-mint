# Sticker Auto Mint Bot

Автоматизированная система для покупки стикеров на платформе Stickerdom с поддержкой TON и Telegram Stars.

## Возможности

- **Параллельные платежи** - одновременная покупка через TON и Telegram Stars
- **Автоматическое отслеживание** коллекций и персонажей
- **CAPTCHA решение** через Anti-captcha.com
- **Умное управление лимитами** с защитой от блокировок API
- **Telegram уведомления** о статусе операций

## Быстрый старт

### Установка
```bash
git clone <repository-url>
cd tgstickers-auto-mint
pip install -r requirements.txt
cp env.example .env
```

### Структура проекта
```
tgstickers-auto-mint/
├── main.py                    # Основной исполняемый файл
├── config.py                  # Конфигурация системы
├── run_tests.py              # Запуск всех тестов
├── data/                     # Служебные файлы (БД, сессии)
│   ├── rate_limiter.db       # База данных rate limiter
│   └── *.session             # Сессии Telegram
├── docs/                     # Документация
│   ├── SETUP.md              # Руководство по настройке
│   ├── API.md                # Техническая документация
│   └── images/               # Скриншоты для документации
├── services/                 # Основные сервисы
├── models/                   # Модели данных
├── utils/                    # Утилиты
└── tests/                    # Тесты
```

### Настройка
1. **Получите JWT токен** Stickerdom согласно `docs/SETUP.md`
2. **Настройте методы оплаты** (TON кошелек и/или Telegram Stars)
3. **Протестируйте конфигурацию**: `python main.py 2/19 --test`

### Запуск
```bash
# Непрерывный мониторинг коллекции
python main.py 2/19

# Одноразовая покупка с максимальным использованием баланса
python main.py 2/19 --once

# Быстрые покупки для солдаута (2-3 минуты)
python main.py 2/19 --fast --once

# Агрессивный режим для очень быстрых солдаутов
python main.py 2/19 --aggressive --continuous

# Симуляция без реальных транзакций
python main.py 2/19 --dry-run

# Управление Telegram сессиями
python main.py 1/1 --session-info      # Информация о сессии
python main.py 1/1 --clear-session     # Очистка файлов сессии
python main.py 1/1 --logout-session    # Выход из Telegram
```

### Rate Limiter профили
```bash
# Посмотреть все доступные профили
python main.py 2/19 --list-profiles

# Использовать конкретный профиль
python main.py 2/19 --profile=fast
```

## Платёжные системы

### TON блокчейн
- Кошелек WalletV5R1
- Минимальный баланс: 0.1 TON
- Время подтверждения: 5-30 секунд

### Telegram Stars
- Моментальные платежи через Telethon API
- Прямая интеграция без браузера
- Требует API ключи my.telegram.org

## Документация

- [`docs/SETUP.md`](docs/SETUP.md) - пошаговое руководство по настройке
- [`docs/API.md`](docs/API.md) - техническая документация API и компонентов
- [`tests/TEST_README.md`](tests/TEST_README.md) - описание тестового покрытия

## Поддержка

- **Техническая поддержка**: [Kaiden](https://t.me/kam1teru)
- **Документация настройки**: `docs/SETUP.md`
- **Тестирование**: `python run_tests.py`

## Отдельная благодарность 

**Автору данного телеграм канала за идею:** [enbanends_home](https://t.me/enbanends_home)

## Безопасность

⚠️ **ВАЖНО**: Не коммитьте приватные ключи, токены или seed фразы в репозиторий.

Все конфиденциальные данные хранятся в переменных окружения и автоматически исключаются из git через `.gitignore`.
