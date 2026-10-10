from __future__ import annotations

import logging
import random

import discord
from discord import app_commands
from discord.ext import commands

from config import config
from services.moderation import sanitize_reply
from services.openrouter import BudgetExceeded, OpenRouterError

log = logging.getLogger("controlroom.fun")

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
