# Техническая документация API

## Архитектура системы

### Основные компоненты

```
PurchaseOrchestrator ──→ StickerdomAPI ──→ RateLimiterService
                                              │
                                              ├── Priority Queue (CRITICAL/HIGH/NORMAL/LOW)
                                              ├── Circuit Breaker (защита от 429 ошибок)
                                              ├── Adaptive Backoff (экспоненциальные задержки)
                                              └── Persistent Storage (SQLite)
```

### Rate Limiter система

#### Приоритеты запросов

| Приоритет | Значение | Операции | Timeout |
|-----------|----------|----------|---------|
| `CRITICAL` | 1 | Покупки, платежи | 30s |
| `HIGH` | 2 | Проверка цен, статуса | 15s |
| `NORMAL` | 3 | Информация о коллекциях | 10s |
| `LOW` | 4 | Фоновое обновление | 5s |

#### Circuit Breaker Pattern

**Активация**: 3 последовательные 429 ошибки
**Длительность**: 300s (production) / 5s (test)
**Восстановление**: автоматическое при успешном запросе

#### Обработка экстремальных лимитов

Система автоматически ограничивает retry-after до разумных пределов:
- Production: максимум 300 секунд (5 минут)
- Test: максимум 10 секунд

### Платёжная архитектура

#### TON платежи
- **Компонент**: `TONWalletManager`
- **Endpoint**: `/api/v1/shop/purchase/crypto`
- **Процесс**: валидация → расчёт → транзакция → подтверждение

#### Telegram Stars платежи
- **Компонент**: `TelegramStarsPayment`
- **Endpoint**: `/api/v1/shop/purchase/stars`
- **Процесс**: получение invoice → SendStarsFormRequest → подтверждение
- **Новые возможности**: Система профилей, адаптивное управление сессиями, circuit breaker

## API Endpoints

### Stickerdom API

#### Получение коллекции
```http
GET /api/v1/stickers/{collection_id}
Authorization: Bearer {jwt_token}
```

#### Инициация покупки
```http
POST /api/v1/shop/buy
Content-Type: application/json
Authorization: Bearer {jwt_token}

{
  "sticker_id": 123,
  "payment_method": "TON|STARS"
}
```

#### Подтверждение TON платежа
```http
POST /api/v1/shop/purchase/crypto
Content-Type: application/json
Authorization: Bearer {jwt_token}

{
  "transaction_hash": "hash",
  "purchase_id": "id"
}
```

## Классы и методы

### RateLimiterService

#### Инициализация
```python
def __init__(self, db_path: str = "data/rate_limiter.db", test_mode: bool = False)
```

#### Ключевые методы

**update_from_headers(headers: Dict[str, str], status_code: int)**
- Обновление состояния из HTTP headers
- Поддержка стандартов: `x-ratelimit-remaining`, `x-ratelimit-reset`, `retry-after`

**execute_with_rate_limit(func: Callable, priority: RequestPriority, max_retries: int = 5)**
- Выполнение функции с автоматическим rate limiting
- Priority queue для упорядочивания запросов

**calculate_backoff_delay(attempt: int, base_delay: float = 1.0) -> float**
- Расчёт времени задержки с intelligent capping
- Обработка экстремальных retry-after значений

### PurchaseOrchestrator

#### execute_parallel_purchases()
Координирует параллельные покупки через TON и Stars:
```python
async def execute_parallel_purchases(self, character_id: int) -> List[PurchaseResult]
```

#### get_character_price()
Получает актуальную цену персонажа с кэшированием:
```python
async def get_character_price(self, character_id: int) -> Optional[CharacterPrice]
```

### StarsSessionManager

#### Управление сессиями Stars
```python
def __init__(self, state_file: str = "data/stars_session_state.json")
```

#### Ключевые методы

**record_purchase_attempt(success: bool, response_time: float, error_type: str = None)**
- Запись статистики покупки для адаптивной системы

**get_adaptive_interval() -> float**  
- Вычисление адаптивного интервала на основе качества сессии

**is_circuit_breaker_active() -> bool**
- Проверка состояния circuit breaker защиты

### StarsProfileManager

#### Управление профилями производительности
Предустановленные профили: `conservative`, `balanced`, `aggressive`, `extreme`

**get_active_profile() -> Dict**
- Получение настроек активного профиля

**set_active_profile(profile_name: str)**
- Активация профиля с применением настроек

### StickerdomAPI

#### Назначение приоритетов запросов

| Метод | Приоритет | Обоснование |
|-------|-----------|-------------|
| `initiate_purchase()` | CRITICAL | Покупочные операции |
| `get_character_stars_invoice_url()` | CRITICAL | Создание транзакций |
| `get_character_price()` | HIGH | Актуальные цены |
| `get_collection()` | NORMAL | Общая информация |
| `test_connection()` | LOW | Диагностика |

## Конфигурация

### Переменные окружения Rate Limiter

| Параметр | Значение | Описание |
|----------|----------|----------|
| `RATE_LIMITER_ENABLED` | `true` | Включение системы |
| `RATE_LIMITER_DB_PATH` | `data/rate_limiter.db` | Путь к SQLite базе |
| `RATE_LIMITER_MAX_DELAY` | `300` | Максимальное ожидание (сек) |
| `RATE_LIMITER_CIRCUIT_BREAKER_THRESHOLD` | `3` | Порог активации circuit breaker |
| `RATE_LIMITER_CIRCUIT_BREAKER_TIMEOUT` | `300` | Длительность circuit breaker |

### Переменные окружения Stars

| Параметр | Значение | Описание |
|----------|----------|----------|
| `STARS_PROFILE` | `balanced` | Профиль производительности |
| `STARS_MAX_PURCHASES_PER_SESSION` | `3` | Максимум покупок за сессию |
| `STARS_PURCHASE_INTERVAL` | `2.0` | Интервал между покупками (сек) |
| `STARS_PAYMENT_TIMEOUT` | `120` | Таймаут оплаты Stars (сек) |
| `STARS_ADAPTIVE_LIMITS` | `true` | Адаптивная коррекция интервалов |
| `STARS_CONCURRENT_PURCHASES` | `false` | Параллельные покупки |

### Режимы работы

#### Production Mode
- `max_wait_time`: 300 секунд
- `circuit_breaker_duration`: 300 секунд
- Полное логирование и persistent storage

#### Test Mode
- `max_wait_time`: 10 секунд
- `circuit_breaker_duration`: 5 секунд
- Автоматическое определение по пути БД

## Persistent Storage

### Схема базы данных
```sql
CREATE TABLE rate_limit_state (
    id INTEGER PRIMARY KEY,
    remaining INTEGER,
    reset_timestamp REAL,
    retry_after INTEGER,
    last_updated REAL,
    etag_cache TEXT,
    last_modified_cache TEXT
);

CREATE TABLE request_metrics (
    timestamp REAL,
    endpoint TEXT,
    status_code INTEGER,
    response_time REAL,
    rate_limited BOOLEAN
);
```

## Мониторинг и метрики

### Доступные метрики
- API requests remaining count
- Circuit breaker status
- Queue size monitoring
- Cache hit rates
- Response time tracking

### Логирование
- **DEBUG**: Request-level detail
- **INFO**: State changes и status
- **WARNING**: Rate limit events
- **ERROR**: System failures

## Тестирование

### Unit Tests
```bash
python -m pytest tests/test_rate_limiter.py -v --asyncio-mode=auto
```

### Integration Tests
```bash
python tests/test_rate_limiter_integration.py
```

### Performance Benchmarks

| Сценарий | Время выполнения | Успешность |
|----------|------------------|------------|
| Обычные запросы (5) | ~1.05s | 100% |
| Burst запросы (20) | ~15-25s | 75%+ |
| Эмуляция 3600s | ~20.8s | Circuit breaker |
| Приоритизация | ~0.2s | 100% | 