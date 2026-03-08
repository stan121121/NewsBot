# 📰 News Digest Bot (OpenRouter edition)

Telegram-бот читает каналы через Telethon, фильтрует шум через любую LLM-модель
на **OpenRouter** и присылает только важные новости каждые N часов.

---

## 🚀 Деплой на Railway — пошагово

### 1. Получить токены

| Что | Где |
|-----|-----|
| `BOT_TOKEN` | [@BotFather](https://t.me/BotFather) → /newbot |
| `OPENROUTER_API_KEY` | [openrouter.ai/keys](https://openrouter.ai/keys) |
| `TELEGRAM_API_ID` / `API_HASH` | [my.telegram.org/apps](https://my.telegram.org/apps) |

### 2. Сгенерировать session string (ОДИН РАЗ локально)

```bash
pip install telethon
python generate_session.py
```

Введи API_ID, API_HASH, номер телефона и код из Telegram.
Сохрани полученную строку как `TELEGRAM_SESSION_STRING`.

### 3. Выбрать модель на OpenRouter

| Модель | Цена | Качество |
|--------|------|----------|
| `google/gemini-flash-1.5` | 💚 дёшево | хорошо |
| `openai/gpt-4o-mini` | 💚 дёшево | хорошо |
| `anthropic/claude-3-haiku` | 💛 средне | отлично |
| `anthropic/claude-3.5-sonnet` | 🔴 дороже | максимум |

Вставить в `OPENROUTER_MODEL=...` — без пересборки.

### 4. Деплой на Railway

```bash
npm install -g @railway/cli
railway login
railway init
railway up
```

### 5. Переменные окружения в Railway Dashboard → Variables

```
BOT_TOKEN=
OPENROUTER_API_KEY=sk-or-v1-...
OPENROUTER_MODEL=anthropic/claude-3.5-sonnet
TELEGRAM_API_ID=
TELEGRAM_API_HASH=
TELEGRAM_SESSION_STRING=
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
main.py            ← запуск бота + планировщик APScheduler
handlers.py        ← команды пользователя
scheduler.py       ← задача по расписанию
channel_reader.py  ← Telethon: чтение каналов
summarizer.py      ← OpenRouter: фильтрация и суммаризация
database.py        ← SQLite: пользователи, каналы, логи
config.py          ← настройки из .env
generate_session.py ← разовый скрипт для авторизации Telethon
```

## 📦 Локальный запуск

```bash
pip install -r requirements.txt
cp .env.example .env
# заполни .env
python main.py
```
