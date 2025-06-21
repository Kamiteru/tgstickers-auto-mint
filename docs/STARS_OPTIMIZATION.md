# Stars Payment Optimization

Система оптимизации платежей через Telegram Stars с адаптивным управлением производительностью.

## Профили производительности

### Conservative
```env
STARS_PROFILE=conservative
```
- Покупки за сессию: 2
- Интервал: 5.0 сек
- Применение: Тестирование, минимальный риск

### Balanced (по умолчанию)
```env
STARS_PROFILE=balanced
```
- Покупки за сессию: 3
- Интервал: 2.0 сек
- Применение: Стандартное использование

### Aggressive
```env
STARS_PROFILE=aggressive
```
- Покупки за сессию: 5
- Интервал: 1.0 сек
- Применение: Быстрые дропы

### Extreme
```env
STARS_PROFILE=extreme
```
- Покупки за сессию: 8
- Интервал: 0.5 сек
- Применение: Критические ситуации

## Конфигурация

### Основные параметры
```env
STARS_MAX_PURCHASES_PER_SESSION=3
STARS_PURCHASE_INTERVAL=2.0
STARS_SESSION_COOLDOWN=30
STARS_MAX_RETRY_ATTEMPTS=3
STARS_ADAPTIVE_LIMITS=true
STARS_CONCURRENT_PURCHASES=false
```

### Таймауты
```env
STARS_PAYMENT_TIMEOUT=120
STARS_INVOICE_TIMEOUT=30
```

## Использование

### Командная строка
```bash
python main.py 1/1 --stars-conservative
python main.py 1/1 --stars-balanced
python main.py 1/1 --stars-aggressive
python main.py 1/1 --stars-extreme
```

### Статистика сессии
```bash
python main.py 1/1 --session-info
```

### Сброс сессии
```bash
python main.py 1/1 --logout-session
```

## Адаптивная система

### Circuit Breaker
- Активация: 3 ошибки подряд
- Задержки: 60s → 120s → 180s

### Качество сессии
Автоматическая коррекция интервалов на основе:
- Коэффициента успешности
- Времени отклика API
- Количества ошибок

### Хранение данных
- `data/stars_session_state.json` - статистика сессии
- `data/stars_payment_session.session` - сессия Telethon

## API

### StarsSessionManager
```python
from services.stars_session_manager import get_stars_session_manager

session_manager = get_stars_session_manager()
stats = session_manager.get_session_info()
```

### StarsProfileManager
```python
from services.stars_profiles import get_stars_profile_manager

profile_manager = get_stars_profile_manager()
profile_manager.set_active_profile('aggressive')
```

## Устранение неполадок

### Сброс статистики
```bash
rm data/stars_session_state.json
```

### Переавторизация
```bash
python main.py 1/1 --logout-session
python main.py 1/1 --test
```