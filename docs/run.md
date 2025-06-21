# Запуск

## Основные команды

### Базовый синтаксис

```bash
python main.py [COLLECTION_ID]/[CHARACTER_ID] [OPTIONS]
```

### Режимы работы

| Команда | Режим | Описание |
|---------|-------|----------|
| `python main.py 2/19` | Мониторинг | Непрерывное отслеживание коллекции |
| `python main.py 2/19 --once` | Покупка | Одноразовая покупка с использованием всего баланса |
| `python main.py 2/19 --continuous` | Активный | Непрерывные покупки при доступности |
| `python main.py 2/19 --dry-run` | Симуляция | Тестовый прогон без реальных транзакций |
| `python main.py 2/19 --test` | Диагностика | Проверка конфигурации и подключений |

## Rate Limiter профили

| Профиль | Команда | Скорость | Применение |
|---------|---------|----------|------------|
| Safe | `--safe` или `--profile=safe` | Минимальная | Максимальная защита от блокировок |
| Balanced | `--balanced` (по умолчанию) | Умеренная | Оптимальный баланс скорости и безопасности |
| Fast | `--fast` или `--profile=fast` | Высокая | Быстрые солдауты (2-3 минуты) |
| Aggressive | `--aggressive` или `--profile=aggressive` | Очень высокая | Очень быстрые солдауты |
| Extreme | `--extreme` или `--profile=extreme` | Максимальная | Критически быстрые солдауты |

```bash
# Просмотр всех профилей
python main.py 2/19 --list-profiles
```

## Stars профили

| Профиль | Команда | Покупки/сессия | Интервал | Применение |
|---------|---------|----------------|----------|------------|
| Conservative | `--stars-conservative` | 2 | 5.0s | Тестирование |
| Balanced | `--stars-balanced` | 3 | 2.0s | Стандартное использование |
| Aggressive | `--stars-aggressive` | 5 | 1.0s | Быстрые дропы |
| Extreme | `--stars-extreme` | 8 | 0.5s | Критические ситуации |

## Управление сессиями

### Telegram Stars сессии

```bash
# Информация о сессии
python main.py 2/19 --session-info

# Очистка локальных файлов
python main.py 2/19 --clear-session

# Полный выход из Telegram
python main.py 2/19 --logout-session
```

## Тестирование

```bash
# Тест конфигурации
python main.py 2/19 --test

# Тест уведомлений
python main.py 2/19 --test-notifications

# Запуск всех unit тестов
python run_tests.py
```

## Примеры использования

### Быстрый старт

```bash
# Проверка настроек
python main.py 2/19 --test

# Запуск мониторинга с balanced профилем
python main.py 2/19

# Агрессивный режим для быстрых дропов
python main.py 2/19 --aggressive --stars-aggressive
```

### Специальные сценарии

```bash
# Только TON платежи
PAYMENT_METHODS=TON python main.py 2/19

# Только Stars платежи
PAYMENT_METHODS=STARS python main.py 2/19

# Максимальная скорость
python main.py 2/19 --extreme --stars-extreme
```

## Мониторинг работы

### Логи

```bash
# Просмотр логов в реальном времени
tail -f logs/sticker_bot.log

# Поиск ошибок
grep ERROR logs/sticker_bot.log
```

### Статистика

- Rate limiter сохраняет метрики в `data/rate_limiter.db`
- Stars сессии отслеживаются в `data/stars_session_state.json`
- Endpoint статистика в `data/endpoint_manager_state.json`

## Остановка

```bash
# Graceful shutdown
Ctrl+C

# Принудительная остановка
Ctrl+C (дважды)
```

## Следующий шаг

Переходите к разделу [использование](usage.md) для изучения продвинутых функций. 