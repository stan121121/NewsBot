"""
database.py — работа с SQLite (пользователи, каналы, настройки)
"""
import aiosqlite
import logging
from datetime import datetime
from typing import Optional

from config import settings

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, path: str = None):
        self.path = path or settings.DB_PATH

    async def init(self):
        """Создаём таблицы если не существуют."""
        async with aiosqlite.connect(self.path) as db:
            await db.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id     INTEGER PRIMARY KEY,
                    username    TEXT,
                    created_at  TEXT DEFAULT (datetime('now')),
                    active      INTEGER DEFAULT 1,
                    interval_h  INTEGER DEFAULT 4
                );

                CREATE TABLE IF NOT EXISTS channels (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id     INTEGER NOT NULL,
                    username    TEXT NOT NULL,
                    title       TEXT,
                    added_at    TEXT DEFAULT (datetime('now')),
                    UNIQUE(user_id, username)
                );

                CREATE TABLE IF NOT EXISTS digest_log (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id     INTEGER NOT NULL,
                    sent_at     TEXT DEFAULT (datetime('now')),
                    news_count  INTEGER
                );

                CREATE TABLE IF NOT EXISTS seen_posts (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id     INTEGER NOT NULL,
                    channel     TEXT NOT NULL,
                    post_id     INTEGER NOT NULL,
                    UNIQUE(user_id, channel, post_id)
                );
            """)
            await db.commit()
        logger.info("Database initialized: %s", self.path)

    # ── Пользователи ─────────────────────────────────────────────
    async def upsert_user(self, user_id: int, username: Optional[str] = None):
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """INSERT INTO users(user_id, username) VALUES(?,?)
                   ON CONFLICT(user_id) DO UPDATE SET username=excluded.username""",
                (user_id, username),
            )
            await db.commit()

    async def get_all_active_users(self) -> list[dict]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM users WHERE active=1")
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    async def set_user_interval(self, user_id: int, hours: int):
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE users SET interval_h=? WHERE user_id=?", (hours, user_id)
            )
            await db.commit()

    async def get_user(self, user_id: int) -> Optional[dict]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM users WHERE user_id=?", (user_id,))
            row = await cur.fetchone()
            return dict(row) if row else None

    # ── Каналы ───────────────────────────────────────────────────
    async def add_channel(self, user_id: int, username: str, title: str = "") -> bool:
        """Возвращает True если добавлен, False если уже был."""
        try:
            async with aiosqlite.connect(self.path) as db:
                await db.execute(
                    "INSERT INTO channels(user_id, username, title) VALUES(?,?,?)",
                    (user_id, username.lower().lstrip("@"), title),
                )
                await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

    async def remove_channel(self, user_id: int, username: str) -> bool:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                "DELETE FROM channels WHERE user_id=? AND username=?",
                (user_id, username.lower().lstrip("@")),
            )
            await db.commit()
            return cur.rowcount > 0

    async def get_user_channels(self, user_id: int) -> list[str]:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                "SELECT username FROM channels WHERE user_id=?", (user_id,)
            )
            rows = await cur.fetchall()
            return [r[0] for r in rows]

    # ── Seen posts (дедупликация) ─────────────────────────────────
    async def mark_seen(self, user_id: int, channel: str, post_ids: list[int]):
        async with aiosqlite.connect(self.path) as db:
            await db.executemany(
                "INSERT OR IGNORE INTO seen_posts(user_id, channel, post_id) VALUES(?,?,?)",
                [(user_id, channel, pid) for pid in post_ids],
            )
            await db.commit()

    async def filter_new_posts(self, user_id: int, channel: str, post_ids: list[int]) -> list[int]:
        if not post_ids:
            return []
        placeholders = ",".join("?" * len(post_ids))
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                f"SELECT post_id FROM seen_posts WHERE user_id=? AND channel=? AND post_id IN ({placeholders})",
                [user_id, channel, *post_ids],
            )
            seen = {r[0] for r in await cur.fetchall()}
        return [pid for pid in post_ids if pid not in seen]

    # ── Лог дайджестов ───────────────────────────────────────────
    async def log_digest(self, user_id: int, news_count: int):
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT INTO digest_log(user_id, news_count) VALUES(?,?)",
                (user_id, news_count),
            )
            await db.commit()
