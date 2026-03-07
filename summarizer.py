"""
summarizer.py — фильтрация и суммаризация новостей через OpenRouter
с группировкой по категориям.
"""
import json
import logging
from dataclasses import dataclass

import httpx

from channel_reader import Post
from config import settings

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

HEADERS = {
    "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
    "Content-Type": "application/json",
    "HTTP-Referer": "https://github.com/newsdigestbot",
    "X-Title": "News Digest Bot",
}

# Список категорий для использования в промпте и сортировке
CATEGORIES_RU = ["Политика", "Экономика", "Общество", "Технологии",
                 "Спорт", "Культура", "Происшествия", "Наука", "Другое"]
CATEGORIES_EN = ["Politics", "Economy", "Society", "Technology",
                 "Sports", "Culture", "Incidents", "Science", "Other"]

LANG_PROMPTS = {
    "ru": {
        "system": (
            "Ты — умный редактор новостного дайджеста. Твоя задача: из потока постов "
            "отобрать ТОЛЬКО действительно важные новости, отфильтровав:\n"
            "• рекламу и промо-посты\n"
            "• репосты без смысловой ценности\n"
            "• мелкие незначимые события\n"
            "• повторяющийся контент\n"
            "Отвечай СТРОГО в формате JSON-массива. Без пояснений вне JSON. "
            "Без markdown-бэктиков. Только чистый JSON."
        ),
        "user_tmpl": (
            "Вот {count} постов из Telegram-каналов за последние часы.\n"
            "Выбери не более {max_news} самых важных и значимых.\n"
            "Для каждой новости верни объект:\n"
            '  "title"      — заголовок (до 80 символов)\n'
            '  "summary"    — краткое изложение (2–3 предложения)\n'
            '  "importance" — оценка важности 1–10\n'
            '  "channel"    — название канала\n'
            '  "url"        — ссылка на пост\n'
            '  "category"   — категория из списка: {categories}\n\n'
            "Посты:\n{posts_text}\n\n"
            "Верни только JSON-массив, например:\n"
            '[{{"title":"...", "summary":"...", "importance":8, "channel":"...", "url":"...", "category":"Политика"}}]'
        ),
    },
    "en": {
        "system": (
            "You are a smart news digest editor. From a stream of posts select ONLY genuinely "
            "important news, filtering out: ads, reposts without value, minor events, duplicates.\n"
            "Reply STRICTLY as a JSON array. No text outside JSON. No markdown backticks."
        ),
        "user_tmpl": (
            "Here are {count} posts from Telegram channels over the past few hours.\n"
            "Select no more than {max_news} most important ones.\n"
            "For each return:\n"
            '  "title"      — headline (up to 80 chars)\n'
            '  "summary"    — 2–3 sentence summary\n'
            '  "importance" — score 1–10\n'
            '  "channel"    — channel name\n'
            '  "url"        — post link\n'
            '  "category"   — category from list: {categories}\n\n'
            "Posts:\n{posts_text}\n\n"
            "Return only a JSON array:\n"
            '[{{"title":"...", "summary":"...", "importance":8, "channel":"...", "url":"...", "category":"Politics"}}]'
        ),
    },
}


@dataclass
class DigestItem:
    title: str
    summary: str
    importance: int
    channel: str
    url: str
    category: str = "Другое"  # значение по умолчанию


def _format_posts_for_prompt(posts: list[Post]) -> str:
    lines = []
    for i, p in enumerate(posts, 1):
        date_str = p.date.strftime("%d.%m %H:%M")
        text_preview = p.text[:400].replace("\n", " ")
        lines.append(
            f"[{i}] Канал: {p.channel_title} (@{p.channel})\n"
            f"    Дата: {date_str}\n"
            f"    Текст: {text_preview}\n"
            f"    Ссылка: {p.url}"
        )
    return "\n\n".join(lines)


async def summarize_posts(posts: list[Post]) -> list[DigestItem]:
    """Отправить посты в OpenRouter, получить отфильтрованный дайджест с категориями."""
    if not posts:
        return []

    lang = settings.DIGEST_LANGUAGE
    prompts = LANG_PROMPTS.get(lang, LANG_PROMPTS["ru"])

    # Выбираем список категорий в зависимости от языка
    categories_list = CATEGORIES_RU if lang == "ru" else CATEGORIES_EN
    categories_str = ", ".join(categories_list)

    posts_text = _format_posts_for_prompt(posts)
    user_msg = prompts["user_tmpl"].format(
        count=len(posts),
        max_news=settings.MAX_NEWS_IN_DIGEST,
        categories=categories_str,
        posts_text=posts_text,
    )

    payload = {
        "model": settings.OPENROUTER_MODEL,
        "max_tokens": 2000,  # при необходимости можно уменьшить
        "temperature": 0.3,
        "messages": [
            {"role": "system", "content": prompts["system"]},
            {"role": "user",   "content": user_msg},
        ],
    }

    logger.info(
        "Sending %d posts to OpenRouter (model: %s)...",
        len(posts),
        settings.OPENROUTER_MODEL,
    )

    try:
        async with httpx.AsyncClient(timeout=60.0) as http:
            resp = await http.post(OPENROUTER_URL, json=payload, headers=HEADERS)
            resp.raise_for_status()
            data = resp.json()

        raw: str = data["choices"][0]["message"]["content"].strip()

        # Убираем возможные маркдаун-бэктики
        if "```" in raw:
            parts = raw.split("```")
            raw = parts[1] if len(parts) > 1 else parts[0]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        items_data: list[dict] = json.loads(raw)
        items = []
        for d in items_data:
            if not isinstance(d, dict):
                continue
            category = d.get("category", "").strip()
            # Если модель вернула категорию не из списка, заменяем на "Другое"/"Other"
            if category not in categories_list:
                category = "Другое" if lang == "ru" else "Other"
            items.append(
                DigestItem(
                    title=str(d.get("title", "")).strip(),
                    summary=str(d.get("summary", "")).strip(),
                    importance=int(d.get("importance", 5)),
                    channel=str(d.get("channel", "")).strip(),
                    url=str(d.get("url", "")).strip(),
                    category=category,
                )
            )
        items.sort(key=lambda x: x.importance, reverse=True)
        logger.info("Got %d digest items from OpenRouter", len(items))

        # Логируем стоимость если API вернул
        usage = data.get("usage", {})
        if usage:
            logger.info(
                "Tokens used — prompt: %s, completion: %s",
                usage.get("prompt_tokens", "?"),
                usage.get("completion_tokens", "?"),
            )

        return items

    except httpx.HTTPStatusError as e:
        logger.error("OpenRouter HTTP error %s: %s", e.response.status_code, e.response.text)
        return []
    except json.JSONDecodeError as e:
        logger.error("JSON parse error: %s | raw response: %.300s", e, raw if 'raw' in locals() else '')
        return []
    except Exception as e:
        logger.error("Summarization error: %s", e, exc_info=True)
        return []


def _he(text: str) -> str:
    """HTML-escape для Telegram parse_mode=HTML."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def format_digest_message(items: list[DigestItem], lang: str = "ru") -> str:
    """Форматировать дайджест с группировкой по категориям."""
    if not items:
        return "📭 Новостей нет — всё тихо." if lang == "ru" else "📭 No news — all quiet."

    # Группируем новости по категориям
    grouped = {}
    for item in items:
        cat = item.category
        if cat not in grouped:
            grouped[cat] = []
        grouped[cat].append(item)

    # Определяем порядок вывода категорий (на основе предопределённого списка)
    order = CATEGORIES_RU if lang == "ru" else CATEGORIES_EN
    # Добавляем категории, которых нет в order (маловероятно) в конец
    existing_cats = set(grouped.keys())
    sorted_cats = [cat for cat in order if cat in existing_cats] + [cat for cat in existing_cats if cat not in order]

    header = "📰 <b>Дайджест новостей</b>\n\n" if lang == "ru" else "📰 <b>News Digest</b>\n\n"
    lines = [header]

    importance_emoji = {10: "🔴", 9: "🔴", 8: "🟠", 7: "🟠", 6: "🟡", 5: "🟡"}

    for cat in sorted_cats:
        # Заголовок категории
        lines.append(f"<b>{cat}</b>")
        for item in grouped[cat]:
            emoji = importance_emoji.get(item.importance, "🟢")
            lines.append(
                f'{emoji} <b>{_he(item.title)}</b>\n'
                f'{_he(item.summary)}\n'
                f'<i>📣 {_he(item.channel)}</i> | <a href="{item.url}">Читать →</a>\n'
            )
        lines.append("")  # пустая строка между категориями

    model_short = settings.OPENROUTER_MODEL.split("/")[-1]
    footer = (
        f"⏰ <i>Следующий дайджест через {settings.DEFAULT_DIGEST_INTERVAL_HOURS} ч.</i>\n"
        f"🤖 <i>{_he(model_short)}</i>"
    )
    lines.append(footer)

    return "\n".join(lines)
