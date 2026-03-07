"""
handlers.py — команды бота
FIXES:
  - parse_mode="HTML" везде (Markdown ломается на _ в username)
  - parse_channel_input() парсит https://t.me/rbc_news → rbc_news
  - убран дублирующий хендлер AddChannel.waiting_for_username
"""
import logging
import re

from aiogram import Router, F
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove

from config import settings
from scheduler import _send_user_digest
from channel_reader import get_telethon_client

router = Router()
logger = logging.getLogger(__name__)


# ── Утилиты ──────────────────────────────────────────────────────
def parse_channel_input(raw: str) -> str | None:
    """
    Принимает любой формат, возвращает чистый username (строчные, без @).

    Поддерживает:
      https://t.me/rbc_news  →  rbc_news
      t.me/rbc_news          →  rbc_news
      @rbc_news              →  rbc_news
      rbc_news               →  rbc_news
    """
    raw = raw.strip()
    # t.me URL
    m = re.match(r"(?:https?://)?t(?:elegram)?\.me/([A-Za-z0-9_]{3,})", raw, re.IGNORECASE)
    if m:
        return m.group(1).lower()
    # инвайт-ссылки не поддерживаем
    if "joinchat" in raw or "+" in raw:
        return None
    # @username / username
    username = raw.lstrip("@").strip().lower()
    if re.match(r"^[A-Za-z0-9_]{3,}$", username):
        return username
    return None


def he(text: str) -> str:
    """Минимальный HTML-escape для Telegram parse_mode=HTML."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ── FSM ──────────────────────────────────────────────────────────
class AddChannel(StatesGroup):
    waiting_for_username = State()


class SetInterval(StatesGroup):
    waiting_for_hours = State()


# ── Клавиатура ───────────────────────────────────────────────────
def main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Мои каналы"), KeyboardButton(text="➕ Добавить канал")],
            [KeyboardButton(text="🗑 Удалить канал"), KeyboardButton(text="⏱ Интервал")],
            [KeyboardButton(text="📰 Дайджест сейчас"), KeyboardButton(text="ℹ️ Помощь")],
        ],
        resize_keyboard=True,
    )


# ── /start ────────────────────────────────────────────────────────
@router.message(CommandStart())
async def cmd_start(message: Message, db):
    await db.upsert_user(message.from_user.id, message.from_user.username)
    await message.answer(
        "👋 Привет! Я собираю новости из Telegram-каналов и присылаю тебе "
        "только самое важное — без шума.\n\n"
        "<b>Как это работает:</b>\n"
        "1️⃣ Добавь каналы командой /add или кнопкой\n"
        "2️⃣ Каждые несколько часов я читаю новые посты\n"
        "3️⃣ AI отбирает самые важные и присылает дайджест\n\n"
        "Нажми <b>«📰 Дайджест сейчас»</b> чтобы попробовать сразу!",
        parse_mode="HTML",
        reply_markup=main_keyboard(),
    )


# ── /help ─────────────────────────────────────────────────────────
@router.message(Command("help"))
@router.message(F.text == "ℹ️ Помощь")
async def cmd_help(message: Message):
    await message.answer(
        "📖 <b>Команды:</b>\n\n"
        "/add <code>@channel</code> — добавить канал\n"
        "/remove <code>@channel</code> — удалить канал\n"
        "/channels — список каналов\n"
        "/interval <code>часы</code> — изменить интервал (напр. <code>/interval 6</code>)\n"
        "/digest — получить дайджест прямо сейчас\n\n"
        "Форматы для /add:\n"
        "• <code>@bbcrussian</code>\n"
        "• <code>bbcrussian</code>\n"
        "• <code>https://t.me/bbcrussian</code>",
        parse_mode="HTML",
    )


# ── Список каналов ────────────────────────────────────────────────
@router.message(Command("channels"))
@router.message(F.text == "📋 Мои каналы")
async def cmd_channels(message: Message, db):
    channels = await db.get_user_channels(message.from_user.id)
    if not channels:
        await message.answer(
            "У тебя пока нет каналов. Добавь первый через /add или кнопку ➕",
            reply_markup=main_keyboard(),
        )
        return
    lines = "\n".join(f"• @{he(ch)}" for ch in channels)
    await message.answer(
        f"📋 <b>Твои каналы:</b>\n\n{lines}",
        parse_mode="HTML",
        reply_markup=main_keyboard(),
    )


# ── Добавление канала ─────────────────────────────────────────────
@router.message(Command("add"))
@router.message(F.text == "➕ Добавить канал")
async def cmd_add_start(message: Message, state: FSMContext, db):
    parts = message.text.split(maxsplit=1)
    if len(parts) == 2 and parts[0] == "/add":
        await _do_add_channel(message, parts[1], db=db)
        return
    await state.set_state(AddChannel.waiting_for_username)
    await message.answer(
        "Отправь username или ссылку на канал:\n\n"
        "<code>@bbcrussian</code>\n"
        "<code>https://t.me/bbcrussian</code>",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove(),
    )


@router.message(AddChannel.waiting_for_username)
async def cmd_add_username(message: Message, state: FSMContext, db):
    await state.clear()
    await _do_add_channel(message, message.text.strip(), db=db)


async def _do_add_channel(message: Message, raw: str, db=None):
    if db is None:
        return
    username = parse_channel_input(raw)
    if username is None:
        await message.answer(
            "❌ Не удалось распознать канал.\n\n"
            "Отправь в формате <code>@username</code> или <code>https://t.me/username</code>",
            parse_mode="HTML",
            reply_markup=main_keyboard(),
        )
        return
    added = await db.add_channel(message.from_user.id, username)
    if added:
        await message.answer(
            f"✅ Канал <code>@{he(username)}</code> добавлен!",
            parse_mode="HTML",
            reply_markup=main_keyboard(),
        )
    else:
        await message.answer(
            f"⚠️ Канал <code>@{he(username)}</code> уже в списке.",
            parse_mode="HTML",
            reply_markup=main_keyboard(),
        )


# ── Удаление канала ───────────────────────────────────────────────
@router.message(Command("remove"))
@router.message(F.text == "🗑 Удалить канал")
async def cmd_remove(message: Message, db):
    parts = message.text.split(maxsplit=1)
    if len(parts) == 2:
        username = parse_channel_input(parts[1])
        if username:
            removed = await db.remove_channel(message.from_user.id, username)
            if removed:
                await message.answer(
                    f"✅ Канал <code>@{he(username)}</code> удалён.",
                    parse_mode="HTML",
                    reply_markup=main_keyboard(),
                )
            else:
                await message.answer(
                    f"❌ Канал <code>@{he(username)}</code> не найден.",
                    parse_mode="HTML",
                    reply_markup=main_keyboard(),
                )
            return

    channels = await db.get_user_channels(message.from_user.id)
    if not channels:
        await message.answer("У тебя нет каналов для удаления.", reply_markup=main_keyboard())
        return
    lines = "\n".join(f"• @{he(ch)}" for ch in channels)
    await message.answer(
        f"Чтобы удалить канал:\n<code>/remove @username</code>\n\nТвои каналы:\n{lines}",
        parse_mode="HTML",
        reply_markup=main_keyboard(),
    )


# ── Интервал ──────────────────────────────────────────────────────
@router.message(Command("interval"))
@router.message(F.text == "⏱ Интервал")
async def cmd_interval(message: Message, state: FSMContext, db):
    parts = message.text.split()
    if len(parts) >= 2 and parts[1].isdigit():
        hours = int(parts[1])
        if 1 <= hours <= 24:
            await db.set_user_interval(message.from_user.id, hours)
            await message.answer(
                f"✅ Интервал установлен: <b>каждые {hours} ч.</b>",
                parse_mode="HTML",
                reply_markup=main_keyboard(),
            )
        else:
            await message.answer("❌ Введи число от 1 до 24.", reply_markup=main_keyboard())
        return

    user = await db.get_user(message.from_user.id)
    current = user["interval_h"] if user else settings.DEFAULT_DIGEST_INTERVAL_HOURS
    await state.set_state(SetInterval.waiting_for_hours)
    await message.answer(
        f"Текущий интервал: <b>{current} ч.</b>\n\nВведи новый (от 1 до 24 часов):",
        parse_mode="HTML",
        reply_markup=ReplyKeyboardRemove(),
    )


@router.message(SetInterval.waiting_for_hours)
async def cmd_interval_input(message: Message, state: FSMContext, db):
    await state.clear()
    text = message.text.strip()
    if not text.isdigit() or not (1 <= int(text) <= 24):
        await message.answer("❌ Введи число от 1 до 24.", reply_markup=main_keyboard())
        return
    hours = int(text)
    await db.set_user_interval(message.from_user.id, hours)
    await message.answer(
        f"✅ Интервал обновлён: <b>каждые {hours} ч.</b>",
        parse_mode="HTML",
        reply_markup=main_keyboard(),
    )


# ── Дайджест прямо сейчас ─────────────────────────────────────────
@router.message(Command("digest"))
@router.message(F.text == "📰 Дайджест сейчас")
async def cmd_digest_now(message: Message, db):
    channels = await db.get_user_channels(message.from_user.id)
    if not channels:
        await message.answer(
            "📭 Сначала добавь хотя бы один канал через /add",
            reply_markup=main_keyboard(),
        )
        return

    await message.answer("⏳ Собираю новости, это может занять 10–30 секунд...")

    client = await get_telethon_client()
    try:
        await _send_user_digest(
            bot=message.bot,
            db=db,
            client=client,
            user_id=message.from_user.id,
            channels=channels,
            since_hours=settings.DEFAULT_DIGEST_INTERVAL_HOURS,
        )
    except Exception as e:
        logger.error("Manual digest error: %s", e)
        await message.answer(
            f"❌ Ошибка при сборе новостей:\n<code>{he(str(e))}</code>",
            parse_mode="HTML",
            reply_markup=main_keyboard(),
        )
    finally:
        await client.disconnect()
