# FAQ

## Общие вопросы

### Q: Как получить JWT токен Stickerdom?

**A:** Откройте DevTools (F12) на stickerdom.store, авторизуйтесь и найдите заголовок `Authorization: Bearer xxx` в любом API запросе. Подробнее в [конфигурации](config.md).

### Q: Какой минимальный баланс нужен для TON?

**A:** Рекомендуется минимум 0.5 TON для стабильной работы (включая газ на транзакции).

### Q: Можно ли использовать только Stars без TON?

**A:** Да, установите `PAYMENT_METHODS=STARS` в .env файле.

## Ошибки и решения

### Q: Rate limit 429 - что делать?

**A:** Снизьте агрессивность:
```bash
python main.py 2/19 --safe --stars-conservative
```

### Q: Stars сессия не подключается

**A:** Проверьте API ключи и переподключитесь:
```bash
python main.py 2/19 --logout-session
python main.py 2/19 --session-info
```

### Q: CAPTCHA не решается автоматически

**A:** Проверьте API ключ Anti-captcha.com:
```bash
CAPTCHA_ENABLED=true python main.py 2/19 --test
```

### Q: Покупки не выполняются

**A:** Проверьте:
1. Баланс кошелька/Stars
2. Доступность коллекции
3. Правильность ID персонажа

```bash
python main.py 2/19 --test --dry-run
```

## Производительность

### Q: Как ускорить покупки?

**A:** Используйте агрессивные профили:
```bash
python main.py 2/19 --extreme --stars-extreme
```

### Q: Почему медленно работает?

**A:** Проверьте:
- Интернет соединение
- Rate limit статистику
- Загрузку CPU/RAM

### Q: Как увеличить количество покупок?

**A:** Увеличьте лимиты Stars:
```env
STARS_MAX_PURCHASES_PER_SESSION=5
```

## Безопасность

### Q: Безопасно ли передавать seed фразу?

**A:** Seed фраза хранится только локально в .env файле и не передается никуда.

### Q: Могут ли заблокировать аккаунт?

**A:** Rate limiter защищает от блокировок, но используйте разумные профили.

### Q: Как обезопасить Stars аккаунт?

**A:** Используйте отдельный Telegram аккаунт для автоматизации.

## Технические вопросы

### Q: Поддерживается ли Python 3.7?

**A:** Минимальная версия Python 3.8 из-за asyncio улучшений.

### Q: Работает ли на Windows?

**A:** Да, протестировано на Windows 10/11.

### Q: Можно ли запускать несколько экземпляров?

**A:** Да, но с разными конфигурациями и data/ папками.

### Q: Как обновить до новой версии?

**A:** 
```bash
git pull origin main
pip install -r requirements.txt
```

## Мониторинг

### Q: Где смотреть логи?

**A:** 
```bash
tail -f logs/sticker_bot.log
```

### Q: Как проверить статистику rate limiter?

**A:**
```bash
sqlite3 data/rate_limiter.db "SELECT * FROM rate_limit_state ORDER BY id DESC LIMIT 5;"
```

### Q: Как узнать качество Stars сессии?

**A:**
```bash
python main.py 2/19 --session-info
```

## Устранение неполадок

### Q: Бот завис и не отвечает

**A:** 
1. Ctrl+C для остановки
2. Проверьте логи на ошибки
3. Перезапустите с --test

### Q: Файлы сессий повреждены

**A:**
```bash
python main.py 2/19 --clear-session
```

### Q: Ошибки импорта модулей

**A:**
```bash
pip install -r requirements.txt --upgrade
```

## Поддержка

### Q: Где получить помощь?

**A:** 
- Telegram: [@kam1teru](https://t.me/kam1teru)
- GitHub Issues
- Документация в `docs/`

### Q: Как сообщить об ошибке?

**A:** Создайте GitHub Issue с:
- Описанием проблемы
- Логами ошибок
- Конфигурацией (без приватных ключей) 