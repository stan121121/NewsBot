# 📰 News Digest Bot

Telegram-бот, который читает каналы, отфильтровывает шум через Claude AI
и присылает только важные новости каждые N часов.

---

## 🚀 Деплой на Railway — пошагово

### 1. Получить токены

| Что | Где |
|-----|-----|
| `BOT_TOKEN` | [@BotFather](https://t.me/BotFather) → /newbot |
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) |
| `TELEGRAM_API_ID` / `API_HASH` | [my.telegram.org/apps](https://my.telegram.org/apps) |

### 2. Сгенерировать session string (ОДИН РАЗ локально)

```bash
pip install telethon
python generate_session.py
```

Введи API_ID, API_HASH, номер телефона и код — получишь строку.
Сохрани её как `TELEGRAM_SESSION_STRING`.

### 3. Загрузить на Railway

```bash
# Установить Railway CLI
npm install -g @railway/cli

# Залогиниться
railway login

# Создать проект
railway init

# Деплой
railway up
```

### 4. Переменные окружения на Railway

В Railway Dashboard → Variables вставь все из `.env.example`:

```
BOT_TOKEN=...
ANTHROPIC_API_KEY=...
TELEGRAM_API_ID=...
TELEGRAM_API_HASH=...
TELEGRAM_SESSION_STRING=...
DEFAULT_DIGEST_INTERVAL_HOURS=4
POSTS_PER_CHANNEL=20
MAX_NEWS_IN_DIGEST=10
DIGEST_LANGUAGE=ru
```

---

## 💬 Команды бота

| Команда | Действие |
|---------|----------|
| `/start` | Начало работы |
| `/add @channel` | Добавить канал |
| `/remove @channel` | Удалить канал |
| `/channels` | Список каналов |
| `/interval 6` | Дайджест каждые 6 часов |
| `/digest` | Получить дайджест прямо сейчас |

---

## 🏗 Архитектура

```
main.py          ← запуск бота + планировщик
handlers.py      ← команды пользователя
scheduler.py     ← задача по расписанию
channel_reader.py ← Telethon: чтение каналов
summarizer.py    ← Claude AI: фильтрация и суммаризация
database.py      ← SQLite: пользователи, каналы, логи
config.py        ← настройки из .env
```

## 📦 Локальный запуск

```bash
git clone <repo>
cd news_bot
pip install -r requirements.txt
cp .env.example .env
# заполни .env
python main.py
```
