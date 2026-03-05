"""
summarizer.py — фильтрация и суммаризация новостей через Claude AI
"""
import json
import logging
from dataclasses import dataclass

import anthropic

from channel_reader import Post
from config import settings

logger = logging.getLogger(__name__)

client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

LANG_PROMPTS = {
    "ru": {
        "system": (
            "Ты — умный редактор новостного дайджеста. Твоя задача: из потока постов "
            "отобрать ТОЛЬКО действительно важные новости, отфильтровав:\n"
            "• рекламу и промо-посты\n"
            "• репосты без смысловой ценности\n"
            "• мелкие незначимые события\n"
            "• повторяющийся контент\n"
            "Отвечай СТРОГО в формате JSON. Без пояснений вне JSON."
        ),
        "user_tmpl": (
            "Вот {count} постов из Telegram-каналов за последние часы.\n"
            "Выбери не более {max_news} самых важных и значимых.\n"
            "Для каждой новости верни:\n"
            '  "title" — заголовок (до 80 символов)\n'
            '  "summary" — краткое изложение (2–3 предложения)\n'
            '  "importance" — оценка важности 1–10\n'
            '  "channel" — название канала\n'
            '  "url" — ссылка на пост\n\n'
            "Посты:\n{posts_text}\n\n"
            'Верни JSON массив: [{{"title":..., "summary":..., "importance":..., "channel":..., "url":...}}, ...]'
        ),
    },
    "en": {
        "system": (
            "You are a smart news digest editor. Your task: from a stream of posts, "
            "select ONLY genuinely important news, filtering out:\n"
            "• ads and promo posts\n"
            "• reposts without meaningful value\n"
            "• minor insignificant events\n"
            "• duplicate content\n"
            "Reply STRICTLY in JSON format. No explanations outside JSON."
        ),
        "user_tmpl": (
            "Here are {count} posts from Telegram channels over the past few hours.\n"
            "Select no more than {max_news} most important ones.\n"
            "For each news item return:\n"
            '  "title" — headline (up to 80 chars)\n'
            '  "summary" — brief summary (2–3 sentences)\n'
            '  "importance" — importance score 1–10\n'
            '  "channel" — channel name\n'
            '  "url" — link to post\n\n'
            "Posts:\n{posts_text}\n\n"
            'Return a JSON array: [{{"title":..., "summary":..., "importance":..., "channel":..., "url":...}}, ...]'
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
    """Отправить посты в Claude, получить отфильтрованный дайджест."""
    if not posts:
        return []

    lang = settings.DIGEST_LANGUAGE
    prompts = LANG_PROMPTS.get(lang, LANG_PROMPTS["ru"])

    posts_text = _format_posts_for_prompt(posts)
    user_msg = prompts["user_tmpl"].format(
        count=len(posts),
        max_news=settings.MAX_NEWS_IN_DIGEST,
        posts_text=posts_text,
    )

    logger.info("Sending %d posts to Claude for summarization...", len(posts))

    try:
        response = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            system=prompts["system"],
            messages=[{"role": "user", "content": user_msg}],
        )
        raw = response.content[0].text.strip()

        # Убираем возможные маркдаун-бэктики
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        items_data: list[dict] = json.loads(raw)
        items = [
            DigestItem(
                title=d.get("title", ""),
                summary=d.get("summary", ""),
                importance=int(d.get("importance", 5)),
                channel=d.get("channel", ""),
                url=d.get("url", ""),
            )
            for d in items_data
        ]
        # Сортируем по важности
        items.sort(key=lambda x: x.importance, reverse=True)
        logger.info("Got %d digest items from Claude", len(items))
        return items

    except Exception as e:
        logger.error("Summarization error: %s", e)
        return []


def format_digest_message(items: list[DigestItem], lang: str = "ru") -> str:
    """Форматировать дайджест в Telegram-сообщение."""
    if not items:
        if lang == "ru":
            return "📭 Новостей нет — всё тихо."
        return "📭 No news — all quiet."

    header = "📰 *Дайджест новостей*\n\n" if lang == "ru" else "📰 *News Digest*\n\n"
    lines = [header]

    importance_emoji = {10: "🔴", 9: "🔴", 8: "🟠", 7: "🟠", 6: "🟡", 5: "🟡"}

    for i, item in enumerate(items, 1):
        emoji = importance_emoji.get(item.importance, "🟢")
        lines.append(
            f"{emoji} *{item.title}*\n"
            f"{item.summary}\n"
            f"_📣 {item.channel}_ | [Читать →]({item.url})\n"
        )

    footer = "\n⏰ _Следующий дайджест через несколько часов_" if lang == "ru" else "\n⏰ _Next digest in a few hours_"
    lines.append(footer)

    return "\n".join(lines)
