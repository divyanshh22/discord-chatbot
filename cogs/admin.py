from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from config import config

log = logging.getLogger("controlroom.admin")


class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    ai = app_commands.Group(name="ai", description="Control the Control Room AI.")

    @staticmethod
    def _is_admin(interaction: discord.Interaction) -> bool:
        user = interaction.user
        roles = [r.id for r in getattr(user, "roles", [])]
        if config.is_admin(user.id, roles):
            return True
        perms = getattr(user, "guild_permissions", None)
        if perms is not None:
            return bool(perms.manage_guild or perms.manage_channels)
        return False

    async def _deny(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            "yeh command sirf admins ke liye hai, aukaat ke bahar mat jao 😅",
            ephemeral=True,
        )

    @ai.command(name="on", description="Enable AI replies in this channel.")
    @app_commands.guild_only()
    async def ai_on(self, interaction: discord.Interaction) -> None:
        if not self._is_admin(interaction):
            await self._deny(interaction)
            return
        await self.bot.memory.set_channel_ai(
            interaction.channel_id, interaction.guild_id, True
        )
        await interaction.response.send_message(
            f"AI replies ON for {interaction.channel.mention} ✅", ephemeral=True
        )

    @ai.command(name="off", description="Disable AI replies in this channel.")
    @app_commands.guild_only()
    async def ai_off(self, interaction: discord.Interaction) -> None:
        if not self._is_admin(interaction):
            await self._deny(interaction)
            return
        await self.bot.memory.set_channel_ai(
            interaction.channel_id, interaction.guild_id, False
        )
        await interaction.response.send_message(
            f"AI replies OFF for {interaction.channel.mention} 💤", ephemeral=True
        )

    @ai.command(name="status", description="Show the current AI configuration.")
    @app_commands.guild_only()
    async def ai_status(self, interaction: discord.Interaction) -> None:
        if not self._is_admin(interaction):
            await self._deny(interaction)
            return
        m = self.bot.memory
        channel_id = interaction.channel_id
        guild_id = interaction.guild_id
        override = m.channel_override(channel_id)
        if override is None:
            _, auto = self.bot.chat_cog._channel_modes(channel_id, guild_id)
            ai_state = "config default"
        else:
            auto = override
            ai_state = "ON" if override else "OFF"

        embed = discord.Embed(
            title="Echo — status",
            color=discord.Color.green()
            if not m.get_bool_flag("kill_switch")
            else discord.Color.red(),
        )
        embed.add_field(name="Model", value=config.openrouter_model, inline=True)
        embed.add_field(
            name="Kill switch",
            value="ON (all AI off)" if m.get_bool_flag("kill_switch") else "off",
            inline=True,
        )
        embed.add_field(name="This channel AI", value=ai_state, inline=True)
        embed.add_field(
            name="This channel autochat",
            value="ON" if auto else "OFF",
            inline=True,
        )
        embed.add_field(
            name="Guild AI",
            value="ON" if m.guild_ai_enabled(guild_id) else "OFF",
            inline=True,
        )
        embed.add_field(
            name="Guild autochat",
            value="ON" if m.guild_autonomous_enabled(guild_id) else "OFF",
            inline=True,
        )
        embed.add_field(
            name="Requests today",
            value=f"{self.bot.openrouter.requests_today} / {config.daily_request_budget}",
            inline=True,
        )
        embed.add_field(
            name="Autonomous probability",
            value=f"{config.autonomous_probability:.0%}",
            inline=True,
        )
        embed.add_field(
            name="Cooldowns",
            value=(
                f"user {config.user_cooldown:.0f}s · "
                f"global {config.global_cooldown:.0f}s · "
                f"{config.max_responses_per_minute}/min"
            ),
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ai.command(name="clear", description="Clear your stored conversation memory.")
    @app_commands.guild_only()
    async def ai_clear(self, interaction: discord.Interaction) -> None:
        await self.bot.memory.clear_user_all(interaction.user.id)
        await interaction.response.send_message(
            "done, meri yaadein clear kar di teri. ab fresh start 🙂", ephemeral=True
        )

    @ai.command(
        name="autochat", description="Enable/disable spontaneous participation."
    )
    @app_commands.describe(state="Turn autonomous chat on or off.")
    @app_commands.choices(
        state=[
            app_commands.Choice(name="on", value="on"),
            app_commands.Choice(name="off", value="off"),
        ]
    )
    @app_commands.guild_only()
    async def ai_autochat(
        self, interaction: discord.Interaction, state: app_commands.Choice[str]
    ) -> None:
        if not self._is_admin(interaction):
            await self._deny(interaction)
            return
        enabled = state.value == "on"
        await self.bot.memory.set_guild_autonomous(interaction.guild_id, enabled)
        await interaction.response.send_message(
            f"Autonomous chat is now {'ON' if enabled else 'OFF'} in this server.",
            ephemeral=True,
        )

    @ai.command(name="kill", description="Instantly stop all AI replies (kill switch).")
    @app_commands.describe(state="Turn the kill switch on or off.")
    @app_commands.choices(
        state=[
            app_commands.Choice(name="on", value="on"),
            app_commands.Choice(name="off", value="off"),
        ]
    )
    @app_commands.guild_only()
    async def ai_kill(
        self, interaction: discord.Interaction, state: app_commands.Choice[str]
    ) -> None:
        if not self._is_admin(interaction):
            await self._deny(interaction)
            return
        enabled = state.value == "on"
        await self.bot.memory.set_flag("kill_switch", "1" if enabled else "0")
        if enabled:
            msg = "KILL SWITCH ON — bot saans nahi le raha 🛑"
        else:
            msg = "KILL SWITCH OFF — bot wapas zinda hai 🫡"
        await interaction.response.send_message(msg, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCog(bot))
