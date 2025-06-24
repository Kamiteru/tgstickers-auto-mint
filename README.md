# TG Stickers Auto-Mint Bot - Simplified

> Автоматизированный бот для массовой покупки стикеров **Stickerdom** с поддержкой параллельных платежей **TON** и **Telegram Stars**.

---

## Возможности

- Асинхронный мониторинг коллекций и персонажей
- Непрерывные покупки до **sold-out** или исчерпания баланса
- Режим *spam*: до 10 "воркеров" с индивидуальными прокси
- Параллельные платежи TON + Stars в одной сессии
- Автоматическое решение CAPTCHA (Anti-captcha.com)
- Кэш цен и баланса для мгновенной реакции на дроп
- Продвинутая система ретраев с обновлением JWT токена
- Гибкая конфигурация через `.env`

## Архитектура

| Слой              | Класс / Модуль                    | Назначение                                            |
|-------------------|------------------------------------|-------------------------------------------------------|
| API               | `services.api_client.StickerdomAPI`| Запросы к Stickerdom, ретраи, CAPTCHA                  |
| Платёж TON        | `services.ton_wallet.TONWalletManager`| Подпись и отправка транзакций                         |
| Платёж Stars      | `services.telegram_stars.TelegramStarsPayment`| Оплата инвойсов через Telethon                       |
| Оркестрация       | `services.purchase_orchestrator.PurchaseOrchestrator`| Координация покупок, выбор метода оплаты         |
| Многопоточность   | `services.threaded_purchase_manager.ThreadedPurchaseManager`| *Spam-mode* с несколькими воркерами             |
| Мониторинг        | `monitoring.collection_watcher.CollectionWatcher`| Отслеживание статуса коллекции                       |
| Кэш               | `services.cache_manager.StateCache`| Периодическое обновление баланса и цен                |
| Логи              | `utils.logger`                     | Единый формат логов                                   |

## Быстрый старт

```bash
# 1. Установка зависимостей
pip install -r requirements.txt

# 2. Создание файла окружения
cp env.example .env && nano .env

# 3. Проверка конфигурации
python main.py 2/19 --test

# 4. Старт бота
python main.py 2/19                 # стандартный режим
python main.py 2/19 --continuous    # непрерывные покупки
python main.py 2/19 --spam          # параллельный spam-режим
```
*Формат цели*: `character_id/collection_id`, например `2/19`.

## Команды CLI

| Аргумент                     | Описание                                                  |
|------------------------------|-----------------------------------------------------------|
| `--once`                     | Купить максимальное количество единоразово                |
| `--continuous`               | Покупать до sold-out / нулевого баланса                   |
| `--spam --attempts 100`      | 100 параллельных попыток покупок через разные прокси      |
| `--dry-run`                  | Симуляция без транзакций                                  |
| `--test`                     | Проверка конфигурации и соединений                        |
| `--session-info`             | Информация о Telegram-сессии Stars                        |
| `--logout-session` / `--clear-session` | Управление файлами `.session`                   |

## Требования

- Python 3.8+
- **Telethon 1.34+** – Stars платежи
- **anticaptchaofficial 1.0.46+** – решение CAPTCHA (опционально)
- Аккаунт Stickerdom и JWT-токен
- Seed-фраза TON кошелька (если `TON` в `PAYMENT_METHODS`)
- Telegram API ID / Hash / Phone (если `STARS` в `PAYMENT_METHODS`)

## Документация

Подробное руководство по настройке находится в [`docs/SETUP.md`](docs/SETUP.md).

## Поддержка

- **Техническая поддержка**: [Kaiden](https://t.me/kam1teru)
- **Документация**: [docs/](docs/) - полное руководство
- **Issues**: [GitHub Issues](https://github.com/your-repo/issues)

## Благодарности

**Автору идеи**: [enbanends_home](https://t.me/enbanends_home)