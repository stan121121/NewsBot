"""
handlers.py — команды бота
"""
import logging

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


# ── FSM ──────────────────────────────────────────────────────────
class AddChannel(StatesGroup):
    waiting_for_username = State()


class SetInterval(StatesGroup):
    waiting_for_hours = State()


# ── Хелперы ──────────────────────────────────────────────────────
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
        "*Как это работает:*\n"
        "1️⃣ Добавь каналы командой /add или кнопкой\n"
        "2️⃣ Каждые несколько часов я читаю новые посты\n"
        "3️⃣ AI отбирает самые важные и присылает дайджест\n\n"
        "Нажми *«📰 Дайджест сейчас»* чтобы попробовать сразу!",
        parse_mode="Markdown",
        reply_markup=main_keyboard(),
    )


# ── /help ────────────────────────────────────────────────────────
@router.message(Command("help"))
@router.message(F.text == "ℹ️ Помощь")
async def cmd_help(message: Message):
    await message.answer(
        "📖 *Команды:*\n\n"
        "/add `@channel` — добавить канал\n"
        "/remove `@channel` — удалить канал\n"
        "/channels — список каналов\n"
        "/interval `часы` — изменить интервал (напр. `/interval 6`)\n"
        "/digest — получить дайджест прямо сейчас\n\n"
        "Каналы можно добавлять по username (например `@bbcrussian`) "
        "или просто `bbcrussian`.",
        parse_mode="Markdown",
    )


# ── Список каналов ───────────────────────────────────────────────
@router.message(Command("channels"))
@router.message(F.text == "📋 Мои каналы")
async def cmd_channels(message: Message, db):
    channels = await db.get_user_channels(message.from_user.id)
    if not channels:
        await message.answer(
            "У тебя пока нет каналов. Добавь первый через /add или кнопку ➕"
        )
        return
    text = "📋 *Твои каналы:*\n\n" + "\n".join(f"• @{ch}" for ch in channels)
    await message.answer(text, parse_mode="Markdown")


# ── Добавление канала ────────────────────────────────────────────
@router.message(Command("add"))
@router.message(F.text == "➕ Добавить канал")
async def cmd_add_start(message: Message, state: FSMContext):
    # Если username передан сразу: /add @channel
    parts = message.text.split()
    if len(parts) >= 2 and parts[0] == "/add":
        await _do_add_channel(message, parts[1], state)
        return
    await state.set_state(AddChannel.waiting_for_username)
    await message.answer(
        "Отправь username канала (например `@bbcrussian` или `ria_novosti`):",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )


@router.message(AddChannel.waiting_for_username)
async def cmd_add_username(message: Message, state: FSMContext, db):
    await state.clear()
    await _do_add_channel(message, message.text.strip(), db=db)


async def _do_add_channel(message: Message, raw: str, state: FSMContext = None, db=None):
    if db is None:
        # В роутере db приходит через data
        return
    username = raw.lower().lstrip("@").strip()
    if not username:
        await message.answer("❌ Некорректный username.", reply_markup=main_keyboard())
        return

    added = await db.add_channel(message.from_user.id, username)
    if added:
        await message.answer(
            f"✅ Канал @{username} добавлен!\n\nТеперь я буду следить за ним.",
            reply_markup=main_keyboard(),
        )
    else:
        await message.answer(
            f"⚠️ Канал @{username} уже в списке.", reply_markup=main_keyboard()
        )


# Обработчик когда db доступна через middleware
@router.message(AddChannel.waiting_for_username)
async def cmd_add_username_with_db(message: Message, state: FSMContext, db):
    await state.clear()
    username = message.text.strip().lower().lstrip("@")
    if not username:
        await message.answer("❌ Некорректный username.", reply_markup=main_keyboard())
        return
    added = await db.add_channel(message.from_user.id, username)
    if added:
        await message.answer(f"✅ Канал @{username} добавлен!", reply_markup=main_keyboard())
    else:
        await message.answer(f"⚠️ @{username} уже в списке.", reply_markup=main_keyboard())


# ── Удаление канала ──────────────────────────────────────────────
@router.message(Command("remove"))
@router.message(F.text == "🗑 Удалить канал")
async def cmd_remove(message: Message, db):
    parts = message.text.split()
    if len(parts) >= 2:
        username = parts[1].lower().lstrip("@")
        removed = await db.remove_channel(message.from_user.id, username)
        if removed:
            await message.answer(f"✅ Канал @{username} удалён.", reply_markup=main_keyboard())
        else:
            await message.answer(f"❌ Канал @{username} не найден.", reply_markup=main_keyboard())
        return

    channels = await db.get_user_channels(message.from_user.id)
    if not channels:
        await message.answer("У тебя нет каналов для удаления.", reply_markup=main_keyboard())
        return
    text = (
        "Чтобы удалить канал, напиши:\n`/remove @username`\n\n"
        "Твои каналы:\n" + "\n".join(f"• @{ch}" for ch in channels)
    )
    await message.answer(text, parse_mode="Markdown")


# ── Интервал ─────────────────────────────────────────────────────
@router.message(Command("interval"))
@router.message(F.text == "⏱ Интервал")
async def cmd_interval(message: Message, state: FSMContext, db):
    parts = message.text.split()
    if len(parts) >= 2 and parts[1].isdigit():
        hours = int(parts[1])
        if 1 <= hours <= 24:
            await db.set_user_interval(message.from_user.id, hours)
            await message.answer(
                f"✅ Интервал установлен: *каждые {hours} ч.*",
                parse_mode="Markdown",
                reply_markup=main_keyboard(),
            )
        else:
            await message.answer("❌ Введи число от 1 до 24.")
        return

    user = await db.get_user(message.from_user.id)
    current = user["interval_h"] if user else settings.DEFAULT_DIGEST_INTERVAL_HOURS
    await state.set_state(SetInterval.waiting_for_hours)
    await message.answer(
        f"Текущий интервал: *{current} ч.*\n\nВведи новый (от 1 до 24 часов):",
        parse_mode="Markdown",
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
        f"✅ Интервал обновлён: *каждые {hours} ч.*",
        parse_mode="Markdown",
        reply_markup=main_keyboard(),
    )


# ── Дайджест прямо сейчас ────────────────────────────────────────
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
        await message.answer(f"❌ Ошибка при сборе новостей: {e}", reply_markup=main_keyboard())
    finally:
        await client.disconnect()
