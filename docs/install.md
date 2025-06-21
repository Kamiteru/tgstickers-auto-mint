# Установка

## Системные требования

- **Python**: 3.8+
- **Операционная система**: Windows, macOS, Linux
- **Интернет**: Стабильное соединение
- **Браузер**: Chrome (для адаптивных эндпоинтов)
- **Аккаунт**: Активный аккаунт Stickerdom

## Установка зависимостей

```bash
pip install -r requirements.txt
```

## Структура данных

При первом запуске автоматически создается папка `data/` для хранения:
- Базы данных SQLite
- Файлов сессий Telegram
- Состояния системы

## Дополнительные зависимости

### Anti-captcha сервис
1. Регистрация на https://anti-captcha.com
2. Пополнение баланса (минимум $5)
3. Получение API ключа в Settings → API

### Chrome браузер
Необходим для адаптивной системы эндпоинтов:
```bash
# Windows - установить Chrome из официального сайта
# Linux
sudo apt install google-chrome-stable

# macOS
brew install --cask google-chrome
```

## Проверка установки

```bash
# Быстрая проверка
python main.py 1/1 --test

# Проверка всех компонентов
python run_tests.py
```

## Устранение неполадок

### Python версия
```bash
python --version  # Должно быть 3.8+
```

### Зависимости
```bash
pip list | grep -E "(requests|asyncio|telethon|ton)"
```

### Права доступа
```bash
# Linux/macOS
chmod +x main.py
``` 