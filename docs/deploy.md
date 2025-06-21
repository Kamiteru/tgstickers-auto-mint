# Развертывание

## Локальное развертывание

### Системные требования

- Python 3.8+
- 4GB RAM
- 10GB свободного места
- Стабильный интернет

### Подготовка

```bash
# Клонирование
git clone https://github.com/Kamiteru/tgstickers-auto-mint.git
cd tgstickers-auto-mint

# Виртуальное окружение
python -m venv venv
source venv/bin/activate  # Linux/macOS
# или
venv\Scripts\activate     # Windows

# Зависимости
pip install -r requirements.txt
```

### Конфигурация

```bash
cp env.example .env
# Заполните .env файл согласно config.md
```

### Запуск

```bash
python main.py 2/19 --test  # Проверка
python main.py 2/19         # Рабочий режим
```

## Docker развертывание

### Dockerfile

```dockerfile
FROM python:3.9-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
CMD ["python", "main.py", "2/19"]
```

### Docker Compose

```yaml
version: '3.8'
services:
  sticker-bot:
    build: .
    environment:
      - STICKERDOM_JWT_TOKEN=${STICKERDOM_JWT_TOKEN}
      - TON_SEED_PHRASE=${TON_SEED_PHRASE}
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
    restart: unless-stopped
```

## VPS развертывание

### Ubuntu/Debian

```bash
# Обновление системы
sudo apt update && sudo apt upgrade -y

# Python и зависимости
sudo apt install python3 python3-pip python3-venv git -y

# Клонирование проекта
git clone https://github.com/Kamiteru/tgstickers-auto-mint.git
cd tgstickers-auto-mint

# Настройка
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Systemd сервис

```ini
# /etc/systemd/system/sticker-bot.service
[Unit]
Description=Sticker Auto Mint Bot
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/tgstickers-auto-mint
Environment=PATH=/home/ubuntu/tgstickers-auto-mint/venv/bin
ExecStart=/home/ubuntu/tgstickers-auto-mint/venv/bin/python main.py 2/19
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
# Активация сервиса
sudo systemctl enable sticker-bot
sudo systemctl start sticker-bot
sudo systemctl status sticker-bot
```

## Мониторинг

### Логи

```bash
# Системные логи
sudo journalctl -u sticker-bot -f

# Логи приложения
tail -f logs/sticker_bot.log
```

### Здоровье системы

```bash
# Проверка процесса
ps aux | grep main.py

# Использование ресурсов
htop

# Дисковое пространство
df -h
```

## Backup

### Данные для резервирования

```bash
# Важные файлы
tar -czf backup.tar.gz \
  .env \
  data/ \
  logs/
```

### Восстановление

```bash
# Распаковка
tar -xzf backup.tar.gz

# Восстановление прав
chmod 600 .env
```

## Обновление

### Автоматическое

```bash
#!/bin/bash
# update.sh
cd /home/ubuntu/tgstickers-auto-mint
git pull origin main
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart sticker-bot
```

### Ручное

```bash
git pull origin main
pip install -r requirements.txt
sudo systemctl restart sticker-bot
```

## Безопасность

### Настройки файрвола

```bash
# UFW
sudo ufw enable
sudo ufw allow ssh
sudo ufw allow out 443  # HTTPS
sudo ufw allow out 80   # HTTP
```

### Ограничения доступа

```bash
# Права на файлы
chmod 600 .env
chmod 700 data/
``` 