"""
summarizer.py — фильтрация и суммаризация новостей через OpenRouter
с расширенными метаданными (журналистский подход).
"""
import json
import logging
from dataclasses import dataclass
from typing import List

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

# Системный промпт с журналистскими требованиями (русский)
SYSTEM_PROMPT_RU = (
    "Ты — старший редактор новостного дайджеста и аналитик с журналистским бэкграундом. "
    "Журналистика — твоя специализация. Твоя задача: из непрерывного потока постов отбирать ТОЛЬКО действительно важные, "
    "релевантные и проверенные новости, последовательно отфильтровывая:\n"
    "• рекламу и промо-посты (включая нативную и спонсорскую подачу);\n"
    "• репосты, цитаты и мемы без собственной смысловой или фактологической ценности;\n"
    "• мелкие локальные события, не имеющие системного или общественно-значимого эффекта;\n"
    "• повторяющийся контент, дубли и выдержки из уже покрытых материалов.\n"
    "Критерии отбора (важность новости):\n"
    "• влияние — затрагивает значимые группы, отрасли или рынки;\n"
    "• новизна — содержит новую или уточняющую информацию;\n"
    "• проверяемость — факты подтверждаются первичными источниками или надёжными публикациями;\n"
    "• масштаб — региональный, национальный или международный уровень.\n"
    "Требования к формату отобранной заметки (дайджест):\n"
    "• Заголовок — лаконичный, без сенсаций, 1 строка;\n"
    "• Короткая аннотация — 2–3 предложения, что случилось;\n"
    "• Значение — 1–2 пункта: почему это важно и кому;\n"
    "• Источники — минимум одно указание на источник (ссылка или идентификатор);\n"
    "• Метаданные — теги: тема, регион, уровень важности (высокий/средний/низкий), отметка «требует проверки» при необходимости.\n"
    "Оперативные правила:\n"
    "• Игнорируй неподтверждённую информацию; если материал потенциально важен, пометь как «требует проверки» и укажи, какие данные нужны;\n"
    "• Для повторяющихся сюжетов оставляй только наиболее полную и свежую версию;\n"
    "• Соблюдай нейтральный, фактический тон; избегай гипербол и оценочных высказываний;\n"
    "• Дайджест должен быть ёмким и пригодным для сканирования — приоритизируй ясность и релевантность.\n"
    "Если понятно — действуй как редактор-аналитик: отбирай, сжимай, помечай и готовь короткие публикации в заданном формате."
)

# Английская версия (краткий перевод)
SYSTEM_PROMPT_EN = (
    "You are a senior news digest editor and analyst with a journalistic background. "
    "Your task: from a stream of posts, select ONLY genuinely important, relevant, and verified news, filtering out:\n"
    "• ads and promotional posts (including native and sponsored);\n"
    "• reposts, quotes, memes without factual value;\n"
    "• minor local events with no systemic significance;\n"
    "• duplicates and excerpts from already covered materials.\n"
    "Selection criteria (importance): impact, novelty, verifiability, scale.\n"
    "Output format for each news item:\n"
    "• Title (one line)\n"
    "• Summary (2–3 sentences)\n"
    "• Significance (why it matters, 1–2 points)\n"
    "• Sources (at least one reference, link or ID)\n"
    "• Metadata: topic, region, importance level (high/medium/low), needs verification flag if necessary.\n"
    "Rules: ignore unverified info; if potentially important, mark as needs verification; keep only the most complete version of recurring stories; neutral factual tone."
)

USER_TMPL_RU = (
    "Вот {count} постов из Telegram-каналов за последние часы.\n"
    "Выбери не более {max_news} самых важных и значимых.\n"
    "Для каждой новости верни объект со следующими полями:\n"
    '  "title"             — заголовок (до 80 символов)\n'
    '  "summary"           — краткое содержание (2–3 предложения)\n'
    '  "significance"      — почему это важно, кому (1–2 пункта)\n'
    '  "sources"           — массив строк со ссылками на источники (минимум одна, включая ссылку на сам пост)\n'
    '  "topic"             — тема (например, Политика, Экономика, Технологии, Спорт, Культура и т.п.)\n'
    '  "region"            — регион (например, Россия, Мир, США, Европа и т.п.)\n'
    '  "importance"        — уровень важности: "высокий", "средний" или "низкий"\n'
    '  "needs_verification" — булево значение, true если информация требует дополнительной проверки\n'
    '  "channel"           — название канала, откуда взят пост (как в исходных данных)\n'
    '  "url"               — прямая ссылка на пост\n\n'
    "Посты:\n{posts_text}\n\n"
    "Верни только JSON-массив, например:\n"
    '[{{"title":"...", "summary":"...", "significance":"...", "sources":["..."], "topic":"...", "region":"...", "importance":"высокий", "needs_verification":false, "channel":"...", "url":"..."}}]'
)

USER_TMPL_EN = (
    "Here are {count} posts from Telegram channels over the past few hours.\n"
    "Select no more than {max_news} most important ones.\n"
    "For each news item return an object with the following fields:\n"
    '  "title"             — headline (up to 80 chars)\n'
    '  "summary"           — 2–3 sentence summary\n'
    '  "significance"      — why it matters, to whom (1–2 points)\n'
    '  "sources"           — array of source links (at least one, including the post URL)\n'
    '  "topic"             — topic (e.g., Politics, Economy, Technology, Sports, Culture)\n'
    '  "region"            — region (e.g., Russia, World, USA, Europe)\n'
    '  "importance"        — "high", "medium", or "low"\n'
    '  "needs_verification" — boolean, true if information needs further verification\n'
    '  "channel"           — channel name (as in the original post)\n'
    '  "url"               — direct link to the post\n\n'
    "Posts:\n{posts_text}\n\n"
    "Return only a JSON array, e.g.:\n"
    '[{{"title":"...", "summary":"...", "significance":"...", "sources":["..."], "topic":"...", "region":"...", "importance":"high", "needs_verification":false, "channel":"...", "url":"..."}}]'
)


@dataclass
class DigestItem:
    title: str
    summary: str
    significance: str
    sources: List[str]
    topic: str
    region: str
    importance: str          # "высокий", "средний", "низкий"
    needs_verification: bool
    channel: str
    url: str

    @property
    def importance_rank(self) -> int:
        """Числовой ранг для сортировки (3 - высокий, 2 - средний, 1 - низкий)."""
        rank_map = {"высокий": 3, "средний": 2, "низкий": 1}
        return rank_map.get(self.importance.lower(), 1)


def _format_posts_for_prompt(posts: List[Post]) -> str:
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


async def summarize_posts(posts: List[Post]) -> List[DigestItem]:
    if not posts:
        return []

    lang = settings.DIGEST_LANGUAGE.lower()
    if lang == "ru":
        system_prompt = SYSTEM_PROMPT_RU
        user_tmpl = USER_TMPL_RU
    else:
        system_prompt = SYSTEM_PROMPT_EN
        user_tmpl = USER_TMPL_EN

    posts_text = _format_posts_for_prompt(posts)
    user_msg = user_tmpl.format(
        count=len(posts),
        max_news=settings.MAX_NEWS_IN_DIGEST,
        posts_text=posts_text,
    )

    payload = {
        "model": settings.OPENROUTER_MODEL,
        "max_tokens": 2000,
        "temperature": 0.3,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_msg},
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

        raw = data["choices"][0]["message"]["content"].strip()

        # Убираем возможные markdown-бэктики
        if "```" in raw:
            parts = raw.split("```")
            raw = parts[1] if len(parts) > 1 else parts[0]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        items_data = json.loads(raw)
        items = []
        for d in items_data:
            if not isinstance(d, dict):
                continue
            # Извлекаем поля с запасными значениями
            title = str(d.get("title", "")).strip()
            summary = str(d.get("summary", "")).strip()
            significance = str(d.get("significance", "")).strip()
            sources = d.get("sources", [])
            if isinstance(sources, str):
                sources = [sources]
            elif not isinstance(sources, list):
                sources = []
            topic = str(d.get("topic", "Другое")).strip()
            region = str(d.get("region", "Неизвестно")).strip()
            importance = str(d.get("importance", "средний")).strip().lower()
            if importance not in ("высокий", "средний", "низкий"):
                importance = "средний"
            needs_verification = bool(d.get("needs_verification", False))
            channel = str(d.get("channel", "")).strip()
            url = str(d.get("url", "")).strip()

            items.append(DigestItem(
                title=title,
                summary=summary,
                significance=significance,
                sources=sources,
                topic=topic,
                region=region,
                importance=importance,
                needs_verification=needs_verification,
                channel=channel,
                url=url,
            ))
        items.sort(key=lambda x: x.importance_rank, reverse=True)
        logger.info("Got %d digest items from OpenRouter", len(items))

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


def format_digest_message(items: List[DigestItem], lang: str = "ru") -> str:
    if not items:
        return "📭 Новостей нет — всё тихо." if lang == "ru" else "📭 No news — all quiet."

    header = "📰 <b>Дайджест новостей</b>\n\n" if lang == "ru" else "📰 <b>News Digest</b>\n\n"
    lines = [header]

    importance_emoji = {
        "высокий": "🔴",
        "средний": "🟠",
        "низкий": "🟢"
    }

    for item in items:
        emoji = importance_emoji.get(item.importance.lower(), "🟢")
        # Заголовок
        lines.append(f'{emoji} <b>{_he(item.title)}</b>')
        # Аннотация
        lines.append(_he(item.summary))
        # Значение
        if item.significance:
            lines.append(f'<i>Значение:</i> {_he(item.significance)}')
        # Источники
        if item.sources:
            sources_html = " | ".join(
                f'<a href="{_he(src)}">[источник]</a>' if src.startswith("http") else _he(src)
                for src in item.sources
            )
            lines.append(f'<i>Источники:</i> {sources_html}')
        # Метаданные
        meta_parts = []
        if item.topic:
            meta_parts.append(f'Тема: {_he(item.topic)}')
        if item.region:
            meta_parts.append(f'Регион: {_he(item.region)}')
        meta_parts.append(f'Важность: {_he(item.importance)}')
        if item.needs_verification:
            meta_parts.append('⚠️ Требует проверки')
        lines.append(' | '.join(meta_parts))
        lines.append('')  # пустая строка между новостями

    # Подвал
    model_short = settings.OPENROUTER_MODEL.split("/")[-1]
    footer = (
        f"⏰ <i>Следующий дайджест через {settings.DEFAULT_DIGEST_INTERVAL_HOURS} ч.</i>\n"
        f"🤖 <i>{_he(model_short)}</i>"
    )
    lines.append(footer)

    return "\n".join(lines)
