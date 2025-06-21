# CI / Тесты

## Тестовое покрытие

### Unit тесты

```bash
# Запуск всех тестов
python run_tests.py

# Запуск конкретного теста
python -m pytest tests/test_api.py -v

# Тест с покрытием
python -m pytest --cov=services tests/
```

### Интеграционные тесты

```bash
# Тест API подключения
python main.py 2/19 --test

# Тест уведомлений
python main.py 2/19 --test-notifications

# Тест Stars сессии
python main.py 2/19 --session-info
```

## Структура тестов

```
tests/
├── test_api.py                    # API клиент тесты
├── test_captcha.py               # CAPTCHA тесты  
├── test_rate_limiter.py          # Rate limiter тесты
├── test_rate_limiter_integration.py  # Интеграционные тесты
├── test_purchase_orchestrator_refactored.py  # Orchestrator тесты
├── test_wallet.py                # TON wallet тесты
└── run_all_tests.py             # Запуск всех тестов
```

## Автоматизация

### GitHub Actions (пример)

```yaml
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Setup Python
        uses: actions/setup-python@v2
        with:
          python-version: 3.8
      - name: Install dependencies
        run: pip install -r requirements.txt
      - name: Run tests
        run: python run_tests.py
```

### Pre-commit хуки

```bash
# Установка pre-commit
pip install pre-commit
pre-commit install

# Запуск проверок
pre-commit run --all-files
```

## Покрытие кода

Текущее покрытие:
- API клиент: 85%
- Rate limiter: 90%
- Payment strategies: 80%
- Orchestrator: 75%

## Мониторинг качества

### Линтеры

```bash
# Проверка кода
pylint services/
flake8 services/
black --check services/
```

### Статический анализ

```bash
# mypy для проверки типов
mypy services/

# bandit для безопасности
bandit -r services/
``` 