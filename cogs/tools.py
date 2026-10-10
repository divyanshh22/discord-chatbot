from __future__ import annotations

import asyncio
import logging
import re
import time

import discord
from discord import app_commands
from discord.ext import commands

from config import config
from services.moderation import sanitize_reply
from services.openrouter import BudgetExceeded, OpenRouterError

log = logging.getLogger("controlroom.tools")

_AI_UNAVAILABLE = "abhi dimaag set nahi hai bhai, thodi der baad try karo 🧠"

_MIN_REMIND = 5
_MAX_REMIND = 30 * 24 * 3600

_UNIT_SECONDS = {
    "s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1,
    "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
    "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600,
    "d": 86400, "day": 86400, "days": 86400,
}
_DURATION_RE = re.compile(r"(\d+)\s*([a-z]+)", re.IGNORECASE)


def _parse_duration(raw: str) -> int | None:
    raw = (raw or "").strip().lower()
    if not raw:
        return None
    if raw.isdigit():
        return int(raw) * 60
    total = 0
    seen = False
    for value, unit in _DURATION_RE.findall(raw):
        mult = _UNIT_SECONDS.get(unit)
        if mult is None:
            continue
        seen = True
        total += int(value) * mult
    return total if seen and total > 0 else None


def _humanize(seconds: int) -> str:
    parts: list[str] = []
    for label, mult in (("d", 86400), ("h", 3600), ("m", 60), ("s", 1)):
        if seconds >= mult:
            q, seconds = divmod(seconds, mult)
            parts.append(f"{q}{label}")
    return " ".join(parts) or "0s"


class ToolsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._tasks: set[asyncio.Task] = set()
        self._ping_cache: tuple[float, bool | None, int | None, str] | None = None

    def cog_unload(self) -> None:
        for task in list(self._tasks):
            task.cancel()

    # ------------------------------------------------------------------ AI
    async def _generate(
        self,
        interaction: discord.Interaction,
        system: str,
        user: str,
        *,
        limit: int,
    ) -> str | None:
        if not config.ai_configured:
            await interaction.followup.send(_AI_UNAVAILABLE, ephemeral=True)
            return None
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        try:
            text = await self.bot.openrouter.complete(messages)
        except BudgetExceeded:
            await interaction.followup.send(
                "aaj ka AI budget khatam, kal aana 💀", ephemeral=True
            )
            return None
        except OpenRouterError as exc:
            log.error("tools AI failed: %s", exc)
            await interaction.followup.send(_AI_UNAVAILABLE, ephemeral=True)
            return None
        reply = sanitize_reply(text, limit)
        if not reply:
            await interaction.followup.send(
                "kuch gadbad ho gayi, dobara try karo", ephemeral=True
            )
            return None
        return reply

    # ------------------------------------------------------------- /summarize
    @app_commands.command(
        name="summarize",
        description="Is channel ki recent chat ka AI TL;DR nikaalo.",
    )
    @app_commands.describe(count="Kitne recent messages summarize karne hain.")
    @app_commands.guild_only()
    async def summarize(
        self,
        interaction: discord.Interaction,
        count: app_commands.Range[int, 5, 100] = 30,
    ) -> None:
        recent = self.bot.memory.get_recent(interaction.channel_id, count)
        if len(recent) < 2:
            await interaction.response.send_message(
                "is channel mein abhi itni chat nahi hai 🤷", ephemeral=True
            )
            return
        await interaction.response.defer()
        lines = [
            f"{e['author_name']}: {e['content']}"
            for e in recent
            if e.get("content")
        ]
        transcript = "\n".join(lines)
        if len(transcript) > config.context_char_budget:
            transcript = transcript[-config.context_char_budget :]
        system = (
            "You are Echo, a witty Discord homie. Summarize the conversation below "
            "as a short TL;DR in Hinglish. Use 3-5 crisp bullet points covering the "
            "main topics, any decisions, and funny bits. No preamble, no 'here is the "
            "summary', just the bullets."
        )
        reply = await self._generate(interaction, system, transcript, limit=1500)
        if reply is None:
            return
        embed = discord.Embed(
            title="📝 TL;DR",
            description=reply,
            color=discord.Color.blurple(),
        )
        embed.set_footer(text=f"last {len(recent)} messages")
        await interaction.followup.send(embed=embed)

    # --------------------------------------------------------------- /remind
    @app_commands.command(
        name="remind",
        description="Mujhe bol do, main time pe yaad dila dunga.",
    )
    @app_commands.describe(
        when="Kab yaad dilana hai, jaise 10m, 1h30m, 2d.",
        text="Kya yaad dilana hai.",
    )
    async def remind(
        self, interaction: discord.Interaction, when: str, text: str
    ) -> None:
        seconds = _parse_duration(when)
        if seconds is None:
            await interaction.response.send_message(
                "time samajh nahi aaya. aise likho: `10m`, `1h30m`, `2d`, `45s`.",
                ephemeral=True,
            )
            return
        if seconds < _MIN_REMIND:
            await interaction.response.send_message(
                f"kam se kam {_MIN_REMIND} seconds ka reminder de sakta hoon.",
                ephemeral=True,
            )
            return
        if seconds > _MAX_REMIND:
            await interaction.response.send_message(
                "max 30 din ka reminder de sakta hoon.", ephemeral=True
            )
            return

        text = text.strip()[:500]
        task = asyncio.create_task(
            self._reminder(
                seconds=seconds,
                channel_id=interaction.channel_id,
                user_id=interaction.user.id,
                mention=interaction.user.mention,
                text=text,
            )
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        await interaction.response.send_message(
            f"⏰ Theek hai, **{_humanize(seconds)}** baad yaad dila dunga.", ephemeral=True
        )

    async def _reminder(
        self,
        *,
        seconds: int,
        channel_id: int,
        user_id: int,
        mention: str,
        text: str,
    ) -> None:
        try:
            await asyncio.sleep(seconds)
        except asyncio.CancelledError:
            return
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except discord.HTTPException:
                channel = None
        if channel is None:
            log.warning("Reminder channel %s unavailable; dropping.", channel_id)
            return
        try:
            await channel.send(
                f"⏰ {mention} reminder: **{text}**",
                allowed_mentions=discord.AllowedMentions(
                    users=True, roles=False, everyone=False
                ),
            )
        except discord.HTTPException as exc:
            log.warning("Could not deliver reminder: %s", exc)

    # ----------------------------------------------------------------- /ping
    @app_commands.command(
        name="ping",
        description="Bot latency aur AI provider status dekho.",
    )
    async def ping(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        ws = round(self.bot.latency * 1000)
        embed = discord.Embed(
            title="🏓 Pong", color=discord.Color.blurple()
        )
        embed.add_field(name="Gateway", value=f"{ws} ms", inline=True)

        if not config.ai_configured:
            embed.add_field(name="Provider", value="❌ not configured", inline=True)
            await interaction.followup.send(embed=embed)
            return

        host = config.openrouter_base_url.split("//")[-1].split("/")[0]
        embed.add_field(name="Provider", value=f"`{host}`", inline=True)
        embed.add_field(
            name="Model", value=f"`{config.openrouter_model}`", inline=True
        )
        fallbacks = config.openrouter_fallback_models
        if fallbacks:
            embed.add_field(
                name="Fallback", value="`" + "`, `".join(fallbacks) + "`", inline=True
            )
        embed.add_field(
            name="Budget",
            value=f"{self.bot.openrouter.budget_remaining}/{config.daily_request_budget} today",
            inline=True,
        )

        ok, ms, detail = await self._provider_check()
        if ok is True:
            status = f"🟢 {ms} ms"
        elif ok is False:
            status = f"🔴 {detail}"
        else:
            status = f"⚪ {detail}"
        embed.add_field(name="AI latency", value=status, inline=True)

        await interaction.followup.send(embed=embed)

    async def _provider_check(self) -> tuple[bool | None, int | None, str]:
        now = time.monotonic()
        if self._ping_cache and now - self._ping_cache[0] < 15:
            _, ok, ms, detail = self._ping_cache
            return ok, ms, detail

        if not self.bot.openrouter.budget_available():
            result: tuple[bool | None, int | None, str] = (None, None, "budget khatam")
        else:
            start = time.perf_counter()
            try:
                await self.bot.openrouter.complete(
                    [{"role": "user", "content": "Reply with exactly: pong"}],
                    temperature=0.0,
                    max_tokens=16,
                )
            except BudgetExceeded:
                result = (None, None, "budget khatam")
            except OpenRouterError as exc:
                result = (False, None, exc.__class__.__name__)
            except Exception as exc:  # aiohttp and friends
                result = (False, None, exc.__class__.__name__)
            else:
                result = (True, round((time.perf_counter() - start) * 1000), "")

        self._ping_cache = (now, result[0], result[1], result[2])
        return result

    # ------------------------------------------------------------- /translate
    @app_commands.command(
        name="translate",
        description="Text ko kisi bhi language mein translate karo.",
    )
    @app_commands.describe(
        language="Target language, jaise hindi, english, bhojpuri, spanish.",
        text="Jo translate karna hai.",
    )
    async def translate(
        self, interaction: discord.Interaction, language: str, text: str
    ) -> None:
        await interaction.response.defer()
        text = text.strip()[: config.max_input_length]
        system = (
            "You are a professional translator. Translate the user's text into "
            f"{language}. Preserve names, slang and tone. Output ONLY the "
            "translation, with no notes, quotes or explanation."
        )
        reply = await self._generate(interaction, system, text, limit=1900)
        if reply is None:
            return
        await interaction.followup.send(reply)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ToolsCog(bot))
