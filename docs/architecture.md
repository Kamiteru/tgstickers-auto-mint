# Архитектура

## Общая структура

```
tgstickers-auto-mint/
├── main.py                 # Точка входа
├── config.py              # Конфигурация
├── services/              # Основные сервисы
│   ├── api_client.py      # API клиент с rate limiting
│   ├── purchase_orchestrator.py  # Оркестратор покупок
│   ├── payment_strategies.py     # Стратегии платежей
│   ├── payment_factory.py       # Фабрика стратегий
│   ├── rate_limiter.py          # Rate limiter с очередями
│   ├── endpoint_manager.py      # Адаптивные эндпоинты
│   ├── telegram_stars.py        # Telegram Stars API
│   ├── ton_wallet.py           # TON блокчейн
│   └── validators.py           # Валидация и безопасность
├── models/               # Модели данных
├── utils/               # Утилиты
└── tests/              # Тесты
```

## Основные компоненты

### 1. Purchase Orchestrator

**Роль:** Координация покупок между различными стратегиями платежей

**Возможности:**
- Параллельное выполнение TON и Stars стратегий
- Валидация и обработка ошибок
- Управление жизненным циклом покупок

### 2. Payment Strategies

**TON Strategy:**
- Работа с TON блокчейном
- Управление кошельком WalletV5R1
- Расчет газа и балансов

**Stars Strategy:**
- Интеграция с Telethon
- Управление сессиями Telegram
- Обработка invoice URL

### 3. Rate Limiter

**Функции:**
- Приоритетные очереди запросов
- Circuit breaker паттерн
- Персистентное состояние в SQLite
- Адаптивные задержки

### 4. Adaptive Endpoints

**Возможности:**
- Автоматическое обнаружение рабочих эндпоинтов
- Fallback механизмы
- Статистика производительности
- Кэширование ответов

## Паттерны проектирования

### Strategy Pattern
```python
class PaymentStrategy(ABC):
    async def execute_purchase(self, collection_id, character_id, count)
    async def calculate_max_purchases(self, ...)
```

### Factory Pattern
```python
class PaymentMethodFactory:
    def create_all_strategies() -> Dict[str, PaymentStrategy]
```

### Observer Pattern
- Уведомления через Telegram бота
- Логирование событий
- Метрики и мониторинг

## Диаграмма потока данных

```
[User Input] → [Main] → [Orchestrator] → [Payment Strategies]
                          ↓
[Rate Limiter] ← [API Client] ← [Endpoint Manager]
                          ↓
[TON Blockchain] / [Telegram Stars API]
```

## Безопасность

### Валидация
- Входные параметры
- Лимиты транзакций  
- Доступность ресурсов
- Race condition защита

### Изоляция
- Разделение ответственности между компонентами
- Независимые стратегии платежей
- Отказоустойчивость при сбоях

## Производительность

### Кэширование
- Цены персонажей (30 сек TTL)
- Балансы кошельков (5 сек TTL)
- HTTP ответы (conditional requests)

### Асинхронность
- Параллельные покупки
- Неблокирующие операции
- Таймауты для всех операций

## Мониторинг

### Метрики
- Rate limiter статистика
- Endpoint производительность  
- Stars сессии качество
- Транзакции блокчейна

### Логирование
- Структурированные логи
- Разные уровни детализации
- Ротация файлов логов

## Расширяемость

### Новые платежные методы
1. Реализовать `PaymentStrategy`
2. Добавить в `PaymentMethodFactory`  
3. Обновить конфигурацию

### Новые API провайдеры
1. Создать адаптер для API
2. Зарегистрировать эндпоинты
3. Настроить rate limiting

## Следующий шаг

Изучите [CI/тесты](ci.md) для понимания процесса разработки. 