# Установка

## Системные требования

- Python 3.8+
- Git
- 5 ГБ свободного места на диске
- Стабильное интернет-соединение

## Быстрая установка

### 1. Клонирование репозитория

```bash
git clone https://github.com/Kamiteru/tgstickers-auto-mint.git
cd tgstickers-auto-mint
```

### 2. Установка зависимостей

```bash
pip install -r requirements.txt
```

### 3. Создание конфигурации

```bash
cp env.example .env
```

## Проверка установки

```bash
# Проверка работоспособности
python main.py 2/19 --test

# Запуск тестов
python run_tests.py
```

## Возможные проблемы

### Windows

```bash
# Если проблемы с curl_cffi
pip install --upgrade curl-cffi

# Если проблемы с Telethon
pip install --upgrade telethon
```

### Linux/macOS

```bash
# Установка системных зависимостей
sudo apt-get install python3-dev libffi-dev libssl-dev

# Или для macOS
brew install openssl libffi
```

## Структура проекта после установки

```
tgstickers-auto-mint/
├── main.py                    # Основной исполняемый файл
├── config.py                  # Конфигурация системы
├── .env                       # Переменные окружения (создается вручную)
├── data/                      # Создается автоматически
│   ├── rate_limiter.db        # База данных rate limiter
│   └── *.session              # Сессии Telegram
├── docs/                      # Документация
├── services/                  # Основные сервисы
├── models/                    # Модели данных
├── utils/                     # Утилиты
└── tests/                     # Тесты
```

## Следующий шаг

После установки переходите к [конфигурации](config.md) системы. 