"""
scheduler.py — задача по расписанию: собрать новости и отправить дайджест
"""
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramForbiddenError

from channel_reader import fetch_all_user_channels, get_telethon_client
from config import settings
from database import Database
from summarizer import format_digest_message, summarize_posts

logger = logging.getLogger(__name__)


async def run_digest(bot: Bot, db: Database):
    """Основная задача: прогнать дайджест для всех активных пользователей."""
    logger.info("=== Running digest job ===")
    users = await db.get_all_active_users()
    if not users:
        logger.info("No active users, skipping.")
        return

    # Один клиент Telethon на весь прогон
    client = await get_telethon_client()

    try:
        for user in users:
            uid = user["user_id"]
            channels = await db.get_user_channels(uid)
            if not channels:
                continue

            interval_h = user.get("interval_h", settings.DEFAULT_DIGEST_INTERVAL_HOURS)

            try:
                await _send_user_digest(
                    bot=bot,
                    db=db,
                    client=client,
                    user_id=uid,
                    channels=channels,
                    since_hours=interval_h,
                )
            except TelegramForbiddenError:
                logger.warning("User %d blocked the bot, deactivating.", uid)
                # Помечаем как неактивного, не ломаем цикл
            except Exception as e:
                logger.error("Digest error for user %d: %s", uid, e)
    finally:
        await client.disconnect()

    logger.info("=== Digest job done ===")


async def _send_user_digest(bot, db, client, user_id, channels, since_hours):
    posts = await fetch_all_user_channels(
        client,
        channels,
        limit_per_channel=settings.POSTS_PER_CHANNEL,
        since_hours=since_hours,
    )

    if not posts:
        logger.info("User %d: no new posts found.", user_id)
        return

    # Фильтруем уже виденные посты
    new_posts = []
    for post in posts:
        new_ids = await db.filter_new_posts(user_id, post.channel, [post.id])
        if new_ids:
            new_posts.append(post)

    if not new_posts:
        logger.info("User %d: all posts already seen.", user_id)
        return

    digest_items = await summarize_posts(new_posts)

    msg = format_digest_message(digest_items, lang=settings.DIGEST_LANGUAGE)

    await bot.send_message(
        chat_id=user_id,
        text=msg,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )

    # Помечаем посты как виденные
    for post in new_posts:
        await db.mark_seen(user_id, post.channel, [post.id])

    await db.log_digest(user_id, len(digest_items))
    logger.info(
        "User %d: digest sent (%d items from %d posts).",
        user_id,
        len(digest_items),
        len(new_posts),
    )
