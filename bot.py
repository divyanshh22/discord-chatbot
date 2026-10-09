from __future__ import annotations

import asyncio
import logging
import sys
from collections import OrderedDict

import discord
from discord.ext import commands

from config import config
from services.memory import MemoryService
from services.openrouter import OpenRouterClient
from services.runtime import FailureBackoff, RateLimiter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("controlroom")


class ControlRoomBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents, help_command=None)

        self.config = config
        self.memory = MemoryService(
            config.db_path, per_channel_cap=config.per_channel_history_cap
        )
        self.openrouter = OpenRouterClient(config)
        self.limiter = RateLimiter(config)
        self.failure_backoff = FailureBackoff()
        self._message_cache: OrderedDict[int, int] = OrderedDict()

    async def setup_hook(self) -> None:
        await self.memory.init()
        await self.openrouter.start()
        for ext in ("cogs.chat", "cogs.admin"):
            await self.load_extension(ext)
            log.info("Loaded extension %s", ext)
        await self._sync_commands()

    async def _sync_commands(self) -> None:
        try:
            if config.dev_guild_id:
                guild = discord.Object(id=config.dev_guild_id)
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
                log.info(
                    "Synced %d commands to dev guild %s",
                    len(synced),
                    config.dev_guild_id,
                )
            else:
                synced = await self.tree.sync()
                log.info(
                    "Synced %d commands globally (may take a while to appear).",
                    len(synced),
                )
        except discord.HTTPException as exc:
            log.error("Failed to sync commands: %s", exc)

    def remember_message(self, message_id: int, author_id: int) -> None:
        self._message_cache[message_id] = author_id
        while len(self._message_cache) > 5000:
            self._message_cache.popitem(last=False)

    async def on_ready(self) -> None:
        log.info(
            "Logged in as %s (id=%s)", self.user, self.user.id if self.user else "?"
        )
        log.info("Serving %d guild(s).", len(self.guilds))
        await self.change_presence(
            status=discord.Status.online,
            activity=discord.Activity(
                type=discord.ActivityType.watching, name="Menace 👀"
            ),
        )

    async def on_message(self, message: discord.Message) -> None:
        if self.user is not None and message.author.id == self.user.id:
            self.remember_message(message.id, message.author.id)
        await self.process_commands(message)

    async def close(self) -> None:
        log.info("Shutting down...")
        await self.openrouter.close()
        await self.memory.close()
        await super().close()


async def main() -> None:
    fatal = config.fatal_problems()
    if fatal:
        for problem in fatal:
            log.error("Configuration error: %s", problem)
        log.error("Fix your .env file (see .env.example) and try again.")
        sys.exit(1)

    for problem in config.warnings():
        log.error("Configuration warning: %s", problem)
    if not config.ai_configured:
        log.error(
            "AI provider is not configured (missing OPENROUTER_API_KEY). "
            "The bot will start but will not generate replies until it is set."
        )

    bot = ControlRoomBot()
    async with bot:
        await bot.start(config.discord_token)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Interrupted by user.")
