from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from typing import Any

import asyncpg

from config import Config

log = logging.getLogger("controlroom.memory")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id          BIGSERIAL PRIMARY KEY,
    guild_id    BIGINT,
    channel_id  BIGINT NOT NULL,
    author_id   BIGINT NOT NULL,
    author_name TEXT   NOT NULL,
    content     TEXT   NOT NULL,
    is_bot      INTEGER NOT NULL DEFAULT 0,
    created_at  DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_channel ON messages (channel_id, id);

CREATE TABLE IF NOT EXISTS prefs (
    user_id BIGINT NOT NULL,
    key     TEXT   NOT NULL,
    value   TEXT   NOT NULL,
    PRIMARY KEY (user_id, key)
);

CREATE TABLE IF NOT EXISTS roast_optout (
    user_id   BIGINT PRIMARY KEY,
    opted_out INTEGER NOT NULL DEFAULT 0,
    updated_at DOUBLE PRECISION
);

CREATE TABLE IF NOT EXISTS guild_settings (
    guild_id            BIGINT PRIMARY KEY,
    ai_enabled          INTEGER NOT NULL DEFAULT 1,
    autonomous_enabled  INTEGER NOT NULL DEFAULT 1,
    updated_at          DOUBLE PRECISION
);

CREATE TABLE IF NOT EXISTS channel_settings (
    channel_id  BIGINT PRIMARY KEY,
    guild_id    BIGINT,
    ai_enabled  INTEGER NOT NULL DEFAULT 1,
    updated_at  DOUBLE PRECISION
);

CREATE TABLE IF NOT EXISTS bot_flags (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at DOUBLE PRECISION
);
"""


class MemoryService:
    def __init__(self, config: Config, per_channel_cap: int = 60) -> None:
        self._config = config
        self._per_channel_cap = per_channel_cap
        self._buffers: dict[int, deque[dict[str, Any]]] = {}
        self._prefs: dict[tuple[int, str], str] = {}
        self._optout: dict[int, bool] = {}
        self._guild_settings: dict[int, dict[str, bool]] = {}
        self._channel_settings: dict[int, bool] = {}
        self._flags: dict[str, str] = {}
        self._lock = asyncio.Lock()
        self._pool: asyncpg.Pool | None = None

    async def init(self) -> None:
        if not self._config.db_configured:
            log.error(
                "PostgreSQL not configured (set DATABASE_URL or PGPASSWORD); "
                "running with in-memory state only."
            )
            return
        try:
            if self._config.database_url:
                self._pool = await asyncpg.create_pool(
                    dsn=self._config.database_url,
                    min_size=1,
                    max_size=5,
                    command_timeout=30,
                )
            else:
                self._pool = await asyncpg.create_pool(
                    host=self._config.pg_host,
                    port=self._config.pg_port,
                    user=self._config.pg_user,
                    password=self._config.pg_password,
                    database=self._config.pg_database,
                    min_size=1,
                    max_size=5,
                    command_timeout=30,
                )
            async with self._pool.acquire() as conn:
                await conn.execute(_SCHEMA)
            await self._warm_cache()
            log.info("Connected to PostgreSQL.")
        except (asyncpg.PostgresError, OSError) as exc:
            log.error(
                "Could not connect to PostgreSQL (%s); "
                "running with in-memory state only.",
                exc.__class__.__name__,
            )
            self._pool = None

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def _warm_cache(self) -> None:
        assert self._pool is not None
        async with self._pool.acquire() as conn:
            self._guild_settings = {
                row["guild_id"]: {
                    "ai_enabled": bool(row["ai_enabled"]),
                    "autonomous_enabled": bool(row["autonomous_enabled"]),
                }
                for row in await conn.fetch("SELECT * FROM guild_settings")
            }
            self._channel_settings = {
                row["channel_id"]: bool(row["ai_enabled"])
                for row in await conn.fetch("SELECT * FROM channel_settings")
            }
            self._prefs = {
                (row["user_id"], row["key"]): row["value"]
                for row in await conn.fetch("SELECT * FROM prefs")
            }
            self._optout = {
                row["user_id"]: bool(row["opted_out"])
                for row in await conn.fetch("SELECT * FROM roast_optout")
            }
            self._flags = {
                row["key"]: row["value"]
                for row in await conn.fetch("SELECT * FROM bot_flags")
            }

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

        if self._pool is None:
            return
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO messages "
                    "(guild_id, channel_id, author_id, author_name, content, is_bot, created_at) "
                    "VALUES ($1, $2, $3, $4, $5, $6, $7)",
                    guild_id,
                    channel_id,
                    author_id,
                    author_name,
                    content,
                    1 if is_bot else 0,
                    entry["created_at"],
                )
                await conn.execute(
                    "DELETE FROM messages WHERE channel_id = $1 AND id NOT IN "
                    "(SELECT id FROM messages WHERE channel_id = $2 "
                    "ORDER BY id DESC LIMIT $3)",
                    channel_id,
                    channel_id,
                    self._per_channel_cap,
                )
        except (asyncpg.PostgresError, OSError):
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

        if self._pool is None:
            return 0
        try:
            async with self._pool.acquire() as conn:
                status = await conn.execute(
                    "DELETE FROM messages WHERE author_id = $1", user_id
                )
            return int(status.split()[-1])
        except (asyncpg.PostgresError, OSError):
            return 0

    def get_pref(self, user_id: int, key: str, default: str | None = None) -> str | None:
        return self._prefs.get((user_id, key), default)

    async def set_pref(self, user_id: int, key: str, value: str) -> None:
        self._prefs[(user_id, key)] = value
        if self._pool is None:
            return
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO prefs (user_id, key, value) VALUES ($1, $2, $3) "
                    "ON CONFLICT (user_id, key) DO UPDATE SET value = EXCLUDED.value",
                    user_id,
                    key,
                    value,
                )
        except (asyncpg.PostgresError, OSError):
            pass

    def is_roast_optout(self, user_id: int) -> bool:
        return self._optout.get(user_id, False)

    async def set_roast_optout(self, user_id: int, opted_out: bool) -> None:
        self._optout[user_id] = opted_out
        if self._pool is None:
            return
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO roast_optout (user_id, opted_out, updated_at) "
                    "VALUES ($1, $2, $3) ON CONFLICT (user_id) DO UPDATE SET "
                    "opted_out = EXCLUDED.opted_out, updated_at = EXCLUDED.updated_at",
                    user_id,
                    1 if opted_out else 0,
                    time.time(),
                )
        except (asyncpg.PostgresError, OSError):
            pass

    async def clear_user_all(self, user_id: int) -> None:
        await self.clear_user(user_id)
        for key in [k for k in self._prefs if k[0] == user_id]:
            self._prefs.pop(key, None)
        if self._pool is None:
            return
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    "DELETE FROM prefs WHERE user_id = $1", user_id
                )
        except (asyncpg.PostgresError, OSError):
            pass

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
        if self._pool is None:
            return
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO guild_settings "
                    "(guild_id, ai_enabled, autonomous_enabled, updated_at) "
                    "VALUES ($1, $2, $3, $4) ON CONFLICT (guild_id) DO UPDATE SET "
                    "ai_enabled = EXCLUDED.ai_enabled, "
                    "autonomous_enabled = EXCLUDED.autonomous_enabled, "
                    "updated_at = EXCLUDED.updated_at",
                    guild_id,
                    1 if data.get("ai_enabled", True) else 0,
                    1 if data.get("autonomous_enabled", True) else 0,
                    time.time(),
                )
        except (asyncpg.PostgresError, OSError):
            pass

    async def set_channel_ai(
        self, channel_id: int, guild_id: int | None, enabled: bool
    ) -> None:
        self._channel_settings[channel_id] = enabled
        if self._pool is None:
            return
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO channel_settings "
                    "(channel_id, guild_id, ai_enabled, updated_at) "
                    "VALUES ($1, $2, $3, $4) ON CONFLICT (channel_id) DO UPDATE SET "
                    "ai_enabled = EXCLUDED.ai_enabled, updated_at = EXCLUDED.updated_at",
                    channel_id,
                    guild_id,
                    1 if enabled else 0,
                    time.time(),
                )
        except (asyncpg.PostgresError, OSError):
            pass

    def get_flag(self, key: str, default: str | None = None) -> str | None:
        return self._flags.get(key, default)

    def get_bool_flag(self, key: str, default: bool = False) -> bool:
        raw = self._flags.get(key)
        if raw is None:
            return default
        return raw == "1"

    async def set_flag(self, key: str, value: str) -> None:
        self._flags[key] = value
        if self._pool is None:
            return
        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO bot_flags (key, value, updated_at) "
                    "VALUES ($1, $2, $3) ON CONFLICT (key) DO UPDATE SET "
                    "value = EXCLUDED.value, updated_at = EXCLUDED.updated_at",
                    key,
                    value,
                    time.time(),
                )
        except (asyncpg.PostgresError, OSError):
            pass
