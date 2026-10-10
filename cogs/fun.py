from __future__ import annotations

import logging
import random
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from config import config
from services.moderation import sanitize_reply
from services.openrouter import BudgetExceeded, OpenRouterError

log = logging.getLogger("controlroom.fun")

_AUDIO_EXTENSIONS = {
    ".mp3",
    ".m4a",
    ".wav",
    ".ogg",
    ".opus",
    ".flac",
    ".webm",
    ".mp4",
    ".aac",
}

_AI_UNAVAILABLE = "abhi dimaag set nahi hai bhai, thodi der baad try karo 🧠"

_EIGHT_BALL = [
    "Haan bhai, pakka. 💯",
    "Nahi, bilkul nahi. 💀",
    "Shayad... par ummeed mat rakho.",
    "Signs haan ke hain. 🗿",
    "Bhai ye toh definitely nahi.",
    "Puchh mat, khud hi samajh ja.",
    "Jo hoga acha hoga. 😌",
    "Aaj nahi, kal dekhte hain.",
    "100% haan, no doubt.",
    "Echo kehta hai bhagwan bharose chhod do. 🙏",
]


class FunCog(commands.Cog):
    audio = app_commands.Group(
        name="audio", description="Voice channel me audio files bajao."
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ------------------------------------------------------------------ AI
    async def _ai(self, system: str, user: str) -> str:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        text = await self.bot.openrouter.complete(messages)
        return sanitize_reply(text, config.max_reply_length)

    async def _run_ai(
        self,
        interaction: discord.Interaction,
        system: str,
        user: str,
        *,
        prefix: str = "",
    ) -> None:
        if not config.ai_configured:
            await interaction.followup.send(_AI_UNAVAILABLE, ephemeral=True)
            return
        try:
            reply = await self._ai(system, user)
        except BudgetExceeded:
            await interaction.followup.send(
                "aaj ka AI budget khatam, kal aana 💀", ephemeral=True
            )
            return
        except OpenRouterError as exc:
            log.error("fun command AI failed: %s", exc)
            await interaction.followup.send(_AI_UNAVAILABLE, ephemeral=True)
            return
        if not reply:
            await interaction.followup.send(
                "kuch gadbad ho gayi, dobara try karo", ephemeral=True
            )
            return
        await interaction.followup.send(f"{prefix}{reply}")

    # --------------------------------------------------------------- audio
    def _audio_dir(self) -> Path:
        folder = config.audio_dir
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        return folder

    def _audio_files(self) -> list[Path]:
        folder = config.audio_dir
        if not folder.is_dir():
            return []
        files = [
            f
            for f in folder.iterdir()
            if f.is_file() and f.suffix.lower() in _AUDIO_EXTENSIONS
        ]
        return sorted(files, key=lambda f: f.name.lower())

    def _resolve_audio(self, name: str) -> Path | None:
        folder = self._audio_dir().resolve()
        candidate = (folder / name).resolve()
        try:
            candidate.relative_to(folder)
        except ValueError:
            return None
        if candidate.is_file() and candidate.suffix.lower() in _AUDIO_EXTENSIONS:
            return candidate
        for f in self._audio_files():
            if name.lower() in (f.name.lower(), f.stem.lower()):
                return f
        return None

    async def _audio_ac(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        cur = (current or "").lower()
        choices: list[app_commands.Choice[str]] = []
        for f in self._audio_files():
            if cur in f.name.lower() or cur in f.stem.lower():
                choices.append(app_commands.Choice(name=f.name, value=f.name))
        return choices[:25]

    @audio.command(name="list", description="Audio folder ki saari files dekho.")
    async def audio_list(self, interaction: discord.Interaction) -> None:
        files = self._audio_files()
        if not files:
            await interaction.response.send_message(
                f"audio folder khali hai. `{config.audio_dir}` me files daalo "
                "(.mp3/.wav/.ogg/.m4a/.flac).",
                ephemeral=True,
            )
            return
        listing = "\n".join(f"• {f.name}" for f in files[:50])
        await interaction.response.send_message(
            f"🎧 Available audio ({len(files)}):\n{listing}", ephemeral=True
        )

    @audio.command(name="play", description="Apni voice channel me audio bajao.")
    @app_commands.describe(name="File ka naam (khali chhodo to random bajega).")
    @app_commands.autocomplete(name=_audio_ac)
    @app_commands.guild_only()
    async def audio_play(
        self, interaction: discord.Interaction, name: str | None = None
    ) -> None:
        if not config.voice_enabled:
            await interaction.response.send_message(
                "voice playback off hai.", ephemeral=True
            )
            return
        member = interaction.user
        if (
            not isinstance(member, discord.Member)
            or member.voice is None
            or member.voice.channel is None
        ):
            await interaction.response.send_message(
                "pehle kisi voice channel me join karo 🎧", ephemeral=True
            )
            return
        channel = member.voice.channel

        await interaction.response.defer()

        files = self._audio_files()
        if not files:
            await interaction.followup.send(
                f"audio folder khali hai. `{config.audio_dir}` me files daalo.",
                ephemeral=True,
            )
            return

        if name:
            path = self._resolve_audio(name)
            if path is None:
                await interaction.followup.send(
                    f"'{name}' naam ki audio nahi mili. `/audio list` dekho.",
                    ephemeral=True,
                )
                return
        else:
            path = random.choice(files)

        vc = interaction.guild.voice_client
        try:
            if vc is None:
                vc = await channel.connect()
            elif vc.channel != channel:
                await vc.move_to(channel)
        except Exception as exc:  # noqa: BLE001
            log.error("voice connect failed: %s", exc)
            await interaction.followup.send(
                "voice channel me join nahi kar paya 😔 "
                "(bot ko Connect + Speak permission chahiye).",
                ephemeral=True,
            )
            return

        if vc.is_playing():
            vc.stop()
        try:
            source = discord.FFmpegPCMAudio(
                str(path), executable=config.ffmpeg_executable
            )
            vc.play(source)
        except Exception as exc:  # noqa: BLE001
            log.error("voice play failed: %s", exc)
            await interaction.followup.send(
                "audio play nahi ho paya 😔 (host pe ffmpeg installed hona chahiye).",
                ephemeral=True,
            )
            return

        await interaction.followup.send(f"🎶 Playing `{path.name}` in {channel.mention}")

    @audio.command(name="stop", description="Chal rahi audio rok do.")
    @app_commands.guild_only()
    async def audio_stop(self, interaction: discord.Interaction) -> None:
        vc = interaction.guild.voice_client
        if vc is not None and (vc.is_playing() or vc.is_paused()):
            vc.stop()
            await interaction.response.send_message("⏹️ stop kar diya.")
        else:
            await interaction.response.send_message(
                "kuch chal nahi raha tha.", ephemeral=True
            )

    @audio.command(name="leave", description="Bot ko voice channel se nikaal do.")
    @app_commands.guild_only()
    async def audio_leave(self, interaction: discord.Interaction) -> None:
        vc = interaction.guild.voice_client
        if vc is not None:
            await vc.disconnect()
            await interaction.response.send_message("👋 voice channel se nikal gaya.")
        else:
            await interaction.response.send_message(
                "main voice me hi nahi hoon.", ephemeral=True
            )

    # ------------------------------------------------------------------ fun
    @app_commands.command(name="roast", description="Echo se kisi ko savage roast karwao.")
    @app_commands.describe(member="Jisko roast karna hai.")
    @app_commands.guild_only()
    async def roast(
        self, interaction: discord.Interaction, member: discord.Member
    ) -> None:
        if self.bot.user is not None and member.id == self.bot.user.id:
            await interaction.response.send_message(
                "khud ko roast? thoda self-respect rakho 😭", ephemeral=True
            )
            return
        if self.bot.memory.is_roast_optout(member.id):
            await interaction.response.send_message(
                f"{member.display_name} ne roast off kar rakha hai 🛑", ephemeral=True
            )
            return
        await interaction.response.defer()
        system = (
            "You are Echo, a savage but playful Discord roaster. Output ONLY the "
            "roast: one or two short lines, natural Hinglish, sharp and original. "
            "No preamble, no quotes, no explanation, never mention being an AI. "
            "Keep it funny, never hateful - no slurs about caste, religion, gender, "
            "region or disability."
        )
        user = (
            f"Roast this Discord user: {member.display_name}. "
            "Make it specific, clever and funny."
        )
        await self._run_ai(interaction, system, user, prefix=f"{member.mention} ")

    @app_commands.command(name="wish", description="Kisi ko occasion ke liye wish karo.")
    @app_commands.describe(member="Kisko wish karna hai.", occasion="Jaise birthday, promotion, shaadi.")
    @app_commands.guild_only()
    async def wish(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        occasion: str,
    ) -> None:
        await interaction.response.defer()
        system = (
            "You are Echo. Write ONE warm, genuine, cool wish line. No sarcasm, no "
            "roasting, no backhanded compliments. Explicitly name the occasion. "
            "Hinglish is fine. Output only the wish, no preamble."
        )
        user = f"Wish {member.display_name} for: {occasion}. Max 25 words."
        await self._run_ai(interaction, system, user, prefix=f"{member.mention} ")

    @app_commands.command(name="compliment", description="Kisi ko genuine compliment do.")
    @app_commands.describe(member="Kisko compliment karna hai.")
    @app_commands.guild_only()
    async def compliment(
        self, interaction: discord.Interaction, member: discord.Member
    ) -> None:
        await interaction.response.defer()
        system = (
            "You are Echo. Give ONE warm, genuine and specific compliment. No "
            "roasting, no sarcasm. Natural Hinglish is fine. Output only the "
            "compliment, no preamble."
        )
        user = f"Compliment this Discord user: {member.display_name}. Max 25 words."
        await self._run_ai(interaction, system, user, prefix=f"{member.mention} ")

    @app_commands.command(name="joke", description="Echo se ek joke sunao.")
    @app_commands.guild_only()
    async def joke(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()
        system = (
            "You are Echo, a witty Discord homie. Reply with ONE short funny joke. "
            "Hinglish is fine. No preamble, and do not explain the joke."
        )
        user = "Tell me a joke."
        await self._run_ai(interaction, system, user)

    @app_commands.command(name="8ball", description="Echo se yes/no sawaal poocho.")
    @app_commands.describe(question="Apna sawaal likho.")
    async def eightball(
        self, interaction: discord.Interaction, question: str
    ) -> None:
        answer = random.choice(_EIGHT_BALL)
        await interaction.response.send_message(f"🎱 {answer}")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(FunCog(bot))
