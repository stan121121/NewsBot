"""
channel_reader.py — чтение постов публичных Telegram-каналов

Стратегия: scraping https://t.me/s/{username}
  - НЕ требует Telethon / авторизации
  - Работает для любого публичного канала
  - Не нужны TELEGRAM_API_ID / API_HASH
  - Стабильно работает на Railway

Telethon оставлен только как опциональный резерв (если задан SESSION_STRING).
"""
import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from config import settings

logger = logging.getLogger(__name__)

# Публичный preview-endpoint Telegram (не требует авторизации)
TG_PREVIEW_URL = "https://t.me/s/{username}"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}


@dataclass
class Post:
    id: int
    channel: str
    channel_title: str
    text: str
    date: datetime
    url: str


# ─── Scraper (основной метод) ──────────────────────────────────────────────

def _parse_post_id(url: str) -> int:
    """Извлечь числовой ID поста из URL вида https://t.me/channel/12345"""
    m = re.search(r"/(\d+)$", url)
    return int(m.group(1)) if m else 0


def _parse_datetime(iso: str) -> datetime:
    """Парсим datetime из атрибута datetime HTML-тега <time>."""
    try:
        # Формат: 2024-03-07T10:30:00+00:00
        return datetime.fromisoformat(iso).astimezone(timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)


def _scrape_posts(html: str, channel_username: str) -> list[Post]:
    """Парсим HTML страницы t.me/s/{channel} и возвращаем список Post."""
    soup = BeautifulSoup(html, "html.parser")

    # Название канала
    title_tag = soup.select_one(".tgme_channel_info_header_title")
    channel_title = title_tag.get_text(strip=True) if title_tag else channel_username

    posts: list[Post] = []

    for msg_div in soup.select(".tgme_widget_message"):
        # Ссылка и ID поста
        link_tag = msg_div.select_one(".tgme_widget_message_date")
        if not link_tag:
            continue
        post_url = link_tag.get("href", "")
        post_id = _parse_post_id(post_url)
        if not post_id:
            continue

        # Дата
        time_tag = msg_div.select_one("time")
        post_date = _parse_datetime(time_tag["datetime"]) if time_tag and time_tag.get("datetime") else datetime.now(timezone.utc)

        # Текст (убираем служебные теги, берём только текст)
        text_div = msg_div.select_one(".tgme_widget_message_text")
        if not text_div:
            continue  # пропускаем посты без текста (фото/видео без подписи)

        # Заменяем <br> на \n перед извлечением текста
        for br in text_div.find_all("br"):
            br.replace_with("\n")
        text = text_div.get_text(separator="").strip()

        if not text:
            continue

        posts.append(Post(
            id=post_id,
            channel=channel_username,
            channel_title=channel_title,
            text=text,
            date=post_date,
            url=post_url or f"https://t.me/{channel_username}/{post_id}",
        ))

    return posts


async def fetch_channel_posts(
    channel_username: str,
    limit: int = 20,
    since_hours: int = None,
    http_client: httpx.AsyncClient = None,
) -> list[Post]:
    """Получить последние посты из публичного канала через t.me/s/."""
    url = TG_PREVIEW_URL.format(username=channel_username)
    min_date = (
        datetime.now(timezone.utc) - timedelta(hours=since_hours)
        if since_hours else None
    )

    own_client = http_client is None
    if own_client:
        http_client = httpx.AsyncClient(timeout=20.0, follow_redirects=True)

    try:
        resp = await http_client.get(url, headers=HEADERS)
        if resp.status_code == 200:
            posts = _scrape_posts(resp.text, channel_username)
        elif resp.status_code == 404:
            logger.warning("Канал @%s не найден (404)", channel_username)
            return []
        else:
            logger.warning("@%s: HTTP %d", channel_username, resp.status_code)
            return []
    except httpx.RequestError as e:
        logger.warning("@%s: сетевая ошибка: %s", channel_username, e)
        return []
    finally:
        if own_client:
            await http_client.aclose()

    # Фильтр по дате и лимит
    result = []
    for p in reversed(posts):  # посты в HTML идут от новых к старым, reverseим
        if min_date and p.date < min_date:
            continue
        result.append(p)

    # Берём последние `limit` постов (самые новые)
    result = sorted(result, key=lambda p: p.date, reverse=True)[:limit]
    return result


async def fetch_all_user_channels(
    channels: list[str],
    limit_per_channel: int = None,
    since_hours: int = None,
    # Аргумент client оставлен для совместимости со старым кодом, игнорируется
    client=None,
) -> list[Post]:
    """Собрать посты со всех каналов пользователя."""
    limit = limit_per_channel or settings.POSTS_PER_CHANNEL
    all_posts: list[Post] = []

    # Один HTTP-клиент на все запросы (эффективнее)
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as http:
        for ch in channels:
            posts = await fetch_channel_posts(
                ch, limit=limit, since_hours=since_hours, http_client=http
            )
            all_posts.extend(posts)
            logger.info("Fetched %d posts from @%s", len(posts), ch)
            await asyncio.sleep(0.3)   # вежливая пауза между запросами

    all_posts.sort(key=lambda p: p.date, reverse=True)
    return all_posts


# ─── Заглушки для совместимости (старый код использовал Telethon-клиент) ──

async def get_telethon_client():
    """
    Совместимость: возвращаем None-клиент.
    fetch_all_user_channels теперь не требует Telethon.
    """
    return _DummyClient()


class _DummyClient:
    """Заглушка вместо TelegramClient — scraper не нуждается в клиенте."""
    async def disconnect(self):
        pass
