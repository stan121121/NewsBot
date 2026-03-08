"""
News Digest Bot — главный файл
Запуск: python main.py
"""
import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import settings
from database import Database
from handlers import router
from scheduler import run_digest

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    bot = Bot(token=settings.BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    db = Database()
    await db.init()

    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        run_digest,
        trigger="interval",
        hours=settings.DEFAULT_DIGEST_INTERVAL_HOURS,
        args=[bot, db],
        id="digest_job",
    )
    scheduler.start()

    logger.info("Bot started. Digest interval: %dh", settings.DEFAULT_DIGEST_INTERVAL_HOURS)
    try:
        await dp.start_polling(bot, db=db, scheduler=scheduler)
    finally:
        scheduler.shutdown()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
