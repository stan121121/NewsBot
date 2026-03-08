"""
channel_reader.py — scraping t.me/s/{channel}

БЕЗ внешних зависимостей (bs4 удалён).
Используем только stdlib: html.parser + re
"""
import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from html.parser import HTMLParser

import httpx

from config import settings

logger = logging.getLogger(__name__)

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


# ─── stdlib HTML-парсер ───────────────────────────────────────────

class _TgPageParser(HTMLParser):
    """
    Парсит HTML страницы t.me/s/channel.
    Собирает: название канала, посты (текст, дата, url).
    """

    def __init__(self):
        super().__init__()
        self.channel_title: str = ""
        self.posts: list[dict] = []          # [{url, date_iso, text}]

        # Внутренние флаги
        self._in_title = False               # .tgme_channel_info_header_title
        self._current_post: dict | None = None
        self._in_msg_text = False            # .tgme_widget_message_text
        self._msg_text_depth = 0             # глубина вложенности внутри текстового div
        self._text_buf: list[str] = []

    # ── helpers ──────────────────────────────────────────────────

    @staticmethod
    def _cls(attrs: list) -> str:
        for name, val in attrs:
            if name == "class":
                return val or ""
        return ""

    @staticmethod
    def _attr(attrs: list, key: str) -> str:
        for name, val in attrs:
            if name == key:
                return val or ""
        return ""

    # ── parser callbacks ─────────────────────────────────────────

    def handle_starttag(self, tag: str, attrs: list):
        cls = self._cls(attrs)

        # Название канала
        if "tgme_channel_info_header_title" in cls:
            self._in_title = True
            return

        # Начало блока поста
        if "tgme_widget_message" in cls and "tgme_widget_message_wrap" not in cls:
            self._current_post = {"url": "", "date_iso": "", "text_parts": []}
            return

        if self._current_post is None:
            return

        # Ссылка с датой
        if "tgme_widget_message_date" in cls:
            self._current_post["url"] = self._attr(attrs, "href")
            return

        # Дата
        if tag == "time":
            dt = self._attr(attrs, "datetime")
            if dt and not self._current_post["date_iso"]:
                self._current_post["date_iso"] = dt
            return

        # Начало текстового блока
        if "tgme_widget_message_text" in cls:
            self._in_msg_text = True
            self._msg_text_depth = 1
            self._text_buf = []
            return

        # Внутри текстового блока — отслеживаем глубину
        if self._in_msg_text:
            self._msg_text_depth += 1
            if tag == "br":
                self._text_buf.append("\n")

    def handle_endtag(self, tag: str):
        if self._in_title:
            self._in_title = False
            return

        if self._in_msg_text:
            self._msg_text_depth -= 1
            if self._msg_text_depth <= 0:
                # Закрылся корневой div текста
                self._in_msg_text = False
                if self._current_post is not None:
                    self._current_post["text_parts"] = list(self._text_buf)
                self._text_buf = []

        # Закрытие блока поста (div.tgme_widget_message_wrap или подобный)
        # Сохраняем пост когда накоплены url + date
        if self._current_post and self._current_post.get("url") and self._current_post.get("date_iso"):
            text = "".join(self._current_post.get("text_parts", [])).strip()
            if text and tag == "div":
                self.posts.append({
                    "url": self._current_post["url"],
                    "date_iso": self._current_post["date_iso"],
                    "text": text,
                })
                self._current_post = None

    def handle_data(self, data: str):
        if self._in_title:
            self.channel_title += data
            return
        if self._in_msg_text:
            self._text_buf.append(data)

    def handle_entityref(self, name: str):
        _entities = {"amp": "&", "lt": "<", "gt": ">", "quot": '"', "nbsp": " ", "apos": "'"}
        char = _entities.get(name, "")
        if self._in_msg_text:
            self._text_buf.append(char)

    def handle_charref(self, name: str):
        try:
            char = chr(int(name[1:], 16) if name.startswith("x") else int(name))
        except (ValueError, OverflowError):
            char = ""
        if self._in_msg_text:
            self._text_buf.append(char)


# ─── Regex-парсер как резервный и более надёжный вариант ─────────

def _regex_parse(html: str, channel_username: str) -> list[dict]:
    """
    Резервный парсер на regex — надёжнее для сложных случаев.
    Возвращает список {url, date_iso, text}.
    """
    results = []

    # Разбиваем на блоки постов
    blocks = re.split(r'class="tgme_widget_message\b', html)

    for block in blocks[1:]:
        # URL поста
        url_m = re.search(r'class="tgme_widget_message_date"\s+href="([^"]+)"', block)
        if not url_m:
            url_m = re.search(r'href="(https://t\.me/[^/]+/\d+)"', block)
        url = url_m.group(1) if url_m else ""

        # Дата
        date_m = re.search(r'datetime="([^"]+)"', block)
        date_iso = date_m.group(1) if date_m else ""

        # Текст: берём содержимое .tgme_widget_message_text
        text_m = re.search(
            r'class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>',
            block, re.DOTALL
        )
        if not text_m:
            continue
        raw_text = text_m.group(1)

        # Убираем HTML-теги, заменяем <br> на \n
        raw_text = re.sub(r"<br\s*/?>", "\n", raw_text, flags=re.IGNORECASE)
        raw_text = re.sub(r"<[^>]+>", "", raw_text)

        # Декодируем HTML-сущности
        raw_text = (raw_text
            .replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
            .replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " "))
        raw_text = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), raw_text)
        raw_text = re.sub(r"&#x([0-9a-fA-F]+);", lambda m: chr(int(m.group(1), 16)), raw_text)

        text = raw_text.strip()
        if text and url and date_iso:
            results.append({"url": url, "date_iso": date_iso, "text": text})

    return results


def _extract_title(html: str) -> str:
    m = re.search(r'class="tgme_channel_info_header_title"[^>]*>([^<]+)<', html)
    return m.group(1).strip() if m else ""


def _parse_post_id(url: str) -> int:
    m = re.search(r"/(\d+)$", url)
    return int(m.group(1)) if m else 0


def _parse_dt(iso: str) -> datetime:
    try:
        return datetime.fromisoformat(iso).astimezone(timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)


def _build_posts(raw_items: list[dict], channel_username: str, channel_title: str) -> list[Post]:
    posts = []
    for item in raw_items:
        pid = _parse_post_id(item["url"])
        if not pid:
            continue
        posts.append(Post(
            id=pid,
            channel=channel_username,
            channel_title=channel_title or channel_username,
            text=item["text"],
            date=_parse_dt(item["date_iso"]),
            url=item["url"],
        ))
    return posts


# ─── Публичный API ────────────────────────────────────────────────

async def fetch_channel_posts(
    channel_username: str,
    limit: int = 20,
    since_hours: int = None,
    http_client: httpx.AsyncClient = None,
) -> list[Post]:
    url = TG_PREVIEW_URL.format(username=channel_username)
    min_date = (
        datetime.now(timezone.utc) - timedelta(hours=since_hours)
        if since_hours else None
    )

    own = http_client is None
    if own:
        http_client = httpx.AsyncClient(timeout=20.0, follow_redirects=True)

    try:
        resp = await http_client.get(url, headers=HEADERS)
    except httpx.RequestError as e:
        logger.warning("@%s: сетевая ошибка: %s", channel_username, e)
        return []
    finally:
        if own:
            await http_client.aclose()

    if resp.status_code == 404:
        logger.warning("Канал @%s не найден (404)", channel_username)
        return []
    if resp.status_code != 200:
        logger.warning("@%s: HTTP %d", channel_username, resp.status_code)
        return []

    html = resp.text
    channel_title = _extract_title(html)

    # Сначала пробуем regex-парсер (быстрее и надёжнее для плоского HTML)
    raw_items = _regex_parse(html, channel_username)
    if not raw_items:
        logger.debug("@%s: regex-парсер вернул 0, пробуем HTMLParser", channel_username)
        parser = _TgPageParser()
        parser.feed(html)
        channel_title = parser.channel_title or channel_title
        raw_items = parser.posts

    posts = _build_posts(raw_items, channel_username, channel_title)

    # Фильтр по дате
    if min_date:
        posts = [p for p in posts if p.date >= min_date]

    posts.sort(key=lambda p: p.date, reverse=True)
    return posts[:limit]


async def fetch_all_user_channels(
    channels: list[str],
    limit_per_channel: int = None,
    since_hours: int = None,
    client=None,   # совместимость, не используется
) -> list[Post]:
    limit = limit_per_channel or settings.POSTS_PER_CHANNEL
    all_posts: list[Post] = []

    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as http:
        for ch in channels:
            posts = await fetch_channel_posts(ch, limit=limit, since_hours=since_hours, http_client=http)
            all_posts.extend(posts)
            logger.info("Fetched %d posts from @%s", len(posts), ch)
            await asyncio.sleep(0.3)

    all_posts.sort(key=lambda p: p.date, reverse=True)
    return all_posts


# ─── Заглушка Telethon для совместимости ──────────────────────────

async def get_telethon_client():
    return _DummyClient()


class _DummyClient:
    async def disconnect(self):
        pass
