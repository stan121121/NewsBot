"""
channel_reader.py — чтение постов из Telegram-каналов через Telethon

FIX: "The key is not registered in the system" (ResolveUsernameRequest)
  get_entity() опирается на локальный кеш сессии — если канал там не встречался,
  вылетает ошибка. Решение: явный вызов ResolveUsernameRequest, который всегда
  идёт напрямую в Telegram API.
"""
import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.contacts import ResolveUsernameRequest
from telethon.tl.types import Message, Channel, InputPeerChannel

from config import settings

logger = logging.getLogger(__name__)


@dataclass
class Post:
    id: int
    channel: str
    channel_title: str
    text: str
    date: datetime
    url: str


def is_telethon_configured() -> bool:
    return bool(settings.TELEGRAM_API_ID and settings.TELEGRAM_API_HASH)


async def get_telethon_client() -> TelegramClient:
    """Клиент Telethon из session string — без интерактивной авторизации (Railway)."""
    if not is_telethon_configured():
        raise RuntimeError(
            "TELEGRAM_API_ID и TELEGRAM_API_HASH не заданы. "
            "Добавь их в переменные окружения Railway."
        )
    session = (
        StringSession(settings.TELEGRAM_SESSION_STRING)
        if settings.TELEGRAM_SESSION_STRING
        else StringSession()
    )
    client = TelegramClient(
        session,
        settings.TELEGRAM_API_ID,
        settings.TELEGRAM_API_HASH,
    )
    await client.connect()
    return client


async def _resolve_channel(client: TelegramClient, username: str) -> Channel | None:
    """
    Резолвим канал через прямой API-запрос (обходит кеш сессии).
    Возвращает объект Channel или None при ошибке.
    """
    try:
        result = await client(ResolveUsernameRequest(username))
        # result.chats содержит каналы/группы, result.users — пользователей
        if result.chats:
            return result.chats[0]
        if result.users:
            return result.users[0]
        logger.warning("ResolveUsername @%s: пустой ответ", username)
        return None
    except Exception as e:
        logger.warning("ResolveUsername @%s failed: %s", username, e)
        return None


async def fetch_channel_posts(
    client: TelegramClient,
    channel_username: str,
    limit: int = 20,
    since_hours: int = None,
) -> list[Post]:
    """
    Получить последние посты из канала.
    since_hours — брать только посты не старше N часов (None = без ограничения).
    """
    posts: list[Post] = []

    entity = await _resolve_channel(client, channel_username)
    if entity is None:
        logger.warning("Пропускаем @%s — не удалось получить entity", channel_username)
        return posts

    title: str = getattr(entity, "title", channel_username)

    min_date = None
    if since_hours:
        min_date = datetime.now(timezone.utc) - timedelta(hours=since_hours)

    try:
        async for msg in client.iter_messages(entity, limit=limit):
            if not isinstance(msg, Message):
                continue
            if not msg.text:
                continue
            if min_date and msg.date < min_date:
                break

            url = f"https://t.me/{channel_username}/{msg.id}"
            posts.append(
                Post(
                    id=msg.id,
                    channel=channel_username,
                    channel_title=title,
                    text=msg.text,
                    date=msg.date,
                    url=url,
                )
            )
    except Exception as e:
        logger.warning("iter_messages @%s: %s", channel_username, e)

    return posts


async def fetch_all_user_channels(
    client: TelegramClient,
    channels: list[str],
    limit_per_channel: int = None,
    since_hours: int = None,
) -> list[Post]:
    """Собрать посты со всех каналов пользователя."""
    limit = limit_per_channel or settings.POSTS_PER_CHANNEL
    all_posts: list[Post] = []

    for ch in channels:
        posts = await fetch_channel_posts(client, ch, limit=limit, since_hours=since_hours)
        all_posts.extend(posts)
        logger.info("Fetched %d posts from @%s", len(posts), ch)
        # Небольшая пауза чтобы не флудить Telegram API
        await asyncio.sleep(0.5)

    # Сортируем от новых к старым
    all_posts.sort(key=lambda p: p.date, reverse=True)
    return all_posts
