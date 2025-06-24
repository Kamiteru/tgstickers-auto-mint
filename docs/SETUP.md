# Руководство по установке TG Stickers Auto-Mint

> Все конфиденциальные данные хранятся в переменных окружения `.env`. **Никогда не коммитьте** приватные ключи или токены в публичный репозиторий.


## 1. Установка

```bash
# Клонируем репозиторий
git clone <repo_url>
cd tgstikers-auto-mint-v4

# Устанавливаем зависимости
pip install -r requirements.txt

# Создаём файл окружения
cp env.example .env  # отредактируйте значения под себя
```

## 2. Заполнение .env

| Переменная | Описание |
|------------|----------|
| `STICKERDOM_JWT_TOKEN` | JWT-токен из Local Storage → `token` |
| `PAYMENT_METHODS` | `TON`, `STARS` или `TON,STARS` |
| `TON_SEED_PHRASE` | 24-словная seed-фраза кошелька |
| `TON_ENDPOINT` | `mainnet` / `testnet` |
| `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` | параметры приложения Telegram |
| `TELEGRAM_PHONE` | номер телефона в международном формате |
| `TELEGRAM_SESSION_NAME` | имя `.session` файла (по умолчанию `stars_payment_session`) |
| `CAPTCHA_ENABLED` | `true` / `false` |
| `ANTICAPTCHA_API_KEY` | ключ Anti-captcha (если `CAPTCHA_ENABLED=true`) |
| `GAS_AMOUNT` | комиссия в TON за одну транзакцию |
| `PURCHASE_DELAY` | пауза между последовательными покупками (сек) |
| `COLLECTION_CHECK_INTERVAL` | частота опроса коллекции (сек) |

### Конфигурация прокси

Файл `proxies.txt` в корне проекта, каждый прокси в новой строке:
```
# Форматы поддерживаются
http://user:pass@host:port
socks5://host:port
host:port  # по умолчанию http
```
При наличии файла прокси выбираются случайно для **каждого** HTTP-запроса.

## 3. Проверка конфигурации

```bash
python main.py 2/19 --test  # character_id/collection_id
```

## 4. Режимы запуска

| Команда | Поведение |
|---------|-----------|
| `python main.py 2/19` | Стандартный мониторинг и покупка при появлении товара |
| `--continuous` | Непрерывные покупки до sold-out или отсутствия средств |
| `--spam --attempts N` | Параллельные N попыток через разные прокси |
| `--once` | Одна сессия покупки на доступный баланс |
| `--dry-run` | Симуляция без списания средств |

## 5. Обновление JWT-токена

```bash
python main.py 0/0 --get-token  # откроется браузер, авторизуйтесь
```

## 6. Решение CAPTCHA

При включённой опции бот автоматически отправляет задания в Anti-captcha. Таймаут ожидания регулируется переменной `CAPTCHA_TIMEOUT` (сек).

---

### Частые проблемы

* **429 Too Many Requests** — уменьшите `MAX_RETRIES_PER_REQUEST` или подключите больше прокси.
* **Invalid auth token** — используйте команду получения токена или проверьте срок действия JWT.
* **Insufficient balance** — пополните кошелёк либо счёт Stars.