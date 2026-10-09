from __future__ import annotations

import asyncio
import sqlite3
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Iterable

_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id    INTEGER,
    channel_id  INTEGER NOT NULL,
    author_id   INTEGER NOT NULL,
    author_name TEXT    NOT NULL,
    content     TEXT    NOT NULL,
    is_bot      INTEGER NOT NULL DEFAULT 0,
    created_at  REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_channel ON messages (channel_id, id);

CREATE TABLE IF NOT EXISTS prefs (
    user_id INTEGER NOT NULL,
    key     TEXT    NOT NULL,
    value   TEXT    NOT NULL,
    PRIMARY KEY (user_id, key)
);

CREATE TABLE IF NOT EXISTS roast_optout (
    user_id   INTEGER PRIMARY KEY,
    opted_out INTEGER NOT NULL DEFAULT 0,
    updated_at REAL
);

CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id            INTEGER PRIMARY KEY,
    ai_enabled          INTEGER NOT NULL DEFAULT 1,
    autonomous_enabled  INTEGER NOT NULL DEFAULT 1,
    updated_at          REAL
);

CREATE TABLE IF NOT EXISTS channel_settings (
    channel_id  INTEGER PRIMARY KEY,
    guild_id    INTEGER,
    ai_enabled  INTEGER NOT NULL DEFAULT 1,
    updated_at  REAL
);

CREATE TABLE IF NOT EXISTS bot_flags (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at REAL
);
"""


class MemoryService:
    def __init__(self, db_path: Path, per_channel_cap: int = 60) -> None:
        self._db_path = db_path
        self._per_channel_cap = per_channel_cap
        self._buffers: dict[int, deque[dict[str, Any]]] = {}
        self._prefs: dict[tuple[int, str], str] = {}
        self._optout: dict[int, bool] = {}
        self._guild_settings: dict[int, dict[str, bool]] = {}
        self._channel_settings: dict[int, bool] = {}
        self._flags: dict[str, str] = {}
        self._lock = asyncio.Lock()
        self._conn: sqlite3.Connection | None = None
        self._db_lock = threading.Lock()

    async def init(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        def _open() -> sqlite3.Connection:
            conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.executescript(_SCHEMA)
            conn.commit()
            return conn

        self._conn = await asyncio.to_thread(_open)
        await self._warm_cache()

    async def close(self) -> None:
        if self._conn is not None:
            await asyncio.to_thread(self._conn.close)
            self._conn = None

    async def _warm_cache(self) -> None:
        def _load() -> tuple[
            dict[int, dict[str, bool]],
            dict[int, bool],
            dict[tuple[int, str], str],
            dict[int, bool],
            dict[str, str],
        ]:
            assert self._conn is not None
            cur = self._conn.cursor()
            guilds = {
                row["guild_id"]: {
                    "ai_enabled": bool(row["ai_enabled"]),
                    "autonomous_enabled": bool(row["autonomous_enabled"]),
                }
                for row in cur.execute("SELECT * FROM guild_settings")
            }
            channels = {
                row["channel_id"]: bool(row["ai_enabled"])
                for row in cur.execute("SELECT * FROM channel_settings")
            }
            prefs = {
                (row["user_id"], row["key"]): row["value"]
                for row in cur.execute("SELECT * FROM prefs")
            }
            optout = {
                row["user_id"]: bool(row["opted_out"])
                for row in cur.execute("SELECT * FROM roast_optout")
            }
            flags = {
                row["key"]: row["value"]
                for row in cur.execute("SELECT * FROM bot_flags")
            }
            return guilds, channels, prefs, optout, flags

        (
            self._guild_settings,
            self._channel_settings,
            self._prefs,
            self._optout,
            self._flags,
        ) = await asyncio.to_thread(_load)

    def _execute(self, sql: str, params: Iterable[Any] = ()) -> None:
        assert self._conn is not None
        with self._db_lock:
            self._conn.execute(sql, tuple(params))
            self._conn.commit()

    def _query(self, sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
        assert self._conn is not None
        with self._db_lock:
            return list(self._conn.execute(sql, tuple(params)))

    async def add_message(
        self,
        *,
        channel_id: int,
        author_id: int,
        author_name: str,
        content: str,
        is_bot: bool,
        guild_id: int | None = None,
    ) -> None:
        entry = {
            "author_id": author_id,
            "author_name": author_name,
            "content": content,
            "is_bot": is_bot,
            "created_at": time.time(),
        }
        buf = self._buffers.setdefault(channel_id, deque(maxlen=self._per_channel_cap))
        buf.append(entry)

        def _insert() -> None:
            self._execute(
                "INSERT INTO messages "
                "(guild_id, channel_id, author_id, author_name, content, is_bot, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    guild_id,
                    channel_id,
                    author_id,
                    author_name,
                    content,
                    1 if is_bot else 0,
                    entry["created_at"],
                ),
            )
            self._execute(
                "DELETE FROM messages WHERE channel_id = ? AND id NOT IN "
                "(SELECT id FROM messages WHERE channel_id = ? ORDER BY id DESC LIMIT ?)",
                (channel_id, channel_id, self._per_channel_cap),
            )

        try:
            await asyncio.to_thread(_insert)
        except sqlite3.Error:
            pass

    def get_recent(self, channel_id: int, limit: int) -> list[dict[str, Any]]:
        buf = self._buffers.get(channel_id)
        if not buf:
            return []
        items = list(buf)[-limit:]
        return [
            {
                "author_id": e["author_id"],
                "author_name": e["author_name"],
                "content": e["content"],
                "is_bot": e["is_bot"],
            }
            for e in items
        ]

    def last_human_speaker(self, channel_id: int) -> int | None:
        buf = self._buffers.get(channel_id)
        if not buf:
            return None
        for e in reversed(buf):
            if not e["is_bot"]:
                return int(e["author_id"])
        return None

    async def clear_user(self, user_id: int) -> int:
        for buf in self._buffers.values():
            for e in list(buf):
                if e["author_id"] == user_id:
                    buf.remove(e)

        def _delete() -> int:
            assert self._conn is not None
            with self._db_lock:
                cur = self._conn.execute(
                    "DELETE FROM messages WHERE author_id = ?", (user_id,)
                )
                self._conn.commit()
                return cur.rowcount

        try:
            return await asyncio.to_thread(_delete)
        except sqlite3.Error:
            return 0

    def get_pref(self, user_id: int, key: str, default: str | None = None) -> str | None:
        return self._prefs.get((user_id, key), default)

    async def set_pref(self, user_id: int, key: str, value: str) -> None:
        self._prefs[(user_id, key)] = value
        await asyncio.to_thread(
            self._execute,
            "INSERT INTO prefs (user_id, key, value) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id, key) DO UPDATE SET value = excluded.value",
            (user_id, key, value),
        )

    def is_roast_optout(self, user_id: int) -> bool:
        return self._optout.get(user_id, False)

    async def set_roast_optout(self, user_id: int, opted_out: bool) -> None:
        self._optout[user_id] = opted_out
        await asyncio.to_thread(
            self._execute,
            "INSERT INTO roast_optout (user_id, opted_out, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET opted_out = excluded.opted_out, "
            "updated_at = excluded.updated_at",
            (user_id, 1 if opted_out else 0, time.time()),
        )

    async def clear_user_all(self, user_id: int) -> None:
        await self.clear_user(user_id)

        def _delete_prefs() -> None:
            self._execute("DELETE FROM prefs WHERE user_id = ?", (user_id,))

        await asyncio.to_thread(_delete_prefs)
        for key in [k for k in self._prefs if k[0] == user_id]:
            self._prefs.pop(key, None)

    def guild_ai_enabled(self, guild_id: int | None) -> bool:
        if guild_id is None:
            return True
        return self._guild_settings.get(guild_id, {}).get("ai_enabled", True)

    def guild_autonomous_enabled(self, guild_id: int | None) -> bool:
        if guild_id is None:
            return True
        return self._guild_settings.get(guild_id, {}).get(
            "autonomous_enabled", True
        )

    def channel_ai_enabled(self, channel_id: int, default: bool = True) -> bool:
        return self._channel_settings.get(channel_id, default)

    def channel_override(self, channel_id: int) -> bool | None:
        return self._channel_settings.get(channel_id)

    async def set_guild_ai(self, guild_id: int, enabled: bool) -> None:
        data = self._guild_settings.setdefault(
            guild_id, {"ai_enabled": True, "autonomous_enabled": True}
        )
        data["ai_enabled"] = enabled
        await self._save_guild(guild_id, data)

    async def set_guild_autonomous(self, guild_id: int, enabled: bool) -> None:
        data = self._guild_settings.setdefault(
            guild_id, {"ai_enabled": True, "autonomous_enabled": True}
        )
        data["autonomous_enabled"] = enabled
        await self._save_guild(guild_id, data)

    async def _save_guild(self, guild_id: int, data: dict[str, bool]) -> None:
        await asyncio.to_thread(
            self._execute,
            "INSERT INTO guild_settings (guild_id, ai_enabled, autonomous_enabled, updated_at) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(guild_id) DO UPDATE SET "
            "ai_enabled = excluded.ai_enabled, "
            "autonomous_enabled = excluded.autonomous_enabled, "
            "updated_at = excluded.updated_at",
            (
                guild_id,
                1 if data.get("ai_enabled", True) else 0,
                1 if data.get("autonomous_enabled", True) else 0,
                time.time(),
            ),
        )

    async def set_channel_ai(
        self, channel_id: int, guild_id: int | None, enabled: bool
    ) -> None:
        self._channel_settings[channel_id] = enabled
        await asyncio.to_thread(
            self._execute,
            "INSERT INTO channel_settings (channel_id, guild_id, ai_enabled, updated_at) "
            "VALUES (?, ?, ?, ?) ON CONFLICT(channel_id) DO UPDATE SET "
            "ai_enabled = excluded.ai_enabled, updated_at = excluded.updated_at",
            (channel_id, guild_id, 1 if enabled else 0, time.time()),
        )

    def get_flag(self, key: str, default: str | None = None) -> str | None:
        return self._flags.get(key, default)

    def get_bool_flag(self, key: str, default: bool = False) -> bool:
        raw = self._flags.get(key)
        if raw is None:
            return default
        return raw == "1"

    async def set_flag(self, key: str, value: str) -> None:
        self._flags[key] = value
        await asyncio.to_thread(
            self._execute,
            "INSERT INTO bot_flags (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
            "updated_at = excluded.updated_at",
            (key, value, time.time()),
        )
