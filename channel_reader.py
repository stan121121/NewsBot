"""
channel_reader.py — чтение постов из Telegram-каналов через Telethon
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional

from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.types import Message, Channel

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


async def get_telethon_client() -> TelegramClient:
    """Создаём клиент Telethon из session string (для Railway — без интерактивной авторизации)."""
    session = StringSession(settings.TELEGRAM_SESSION_STRING) if settings.TELEGRAM_SESSION_STRING else StringSession()
    client = TelegramClient(session, settings.TELEGRAM_API_ID, settings.TELEGRAM_API_HASH)
    await client.connect()
    return client


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
    try:
        entity: Channel = await client.get_entity(channel_username)
        title = getattr(entity, "title", channel_username)

        min_date = None
        if since_hours:
            min_date = datetime.now(timezone.utc) - timedelta(hours=since_hours)

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
        logger.warning("Cannot fetch channel %s: %s", channel_username, e)

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

    # Сортируем от новых к старым
    all_posts.sort(key=lambda p: p.date, reverse=True)
    return all_posts
