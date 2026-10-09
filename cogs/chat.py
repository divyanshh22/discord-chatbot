from __future__ import annotations

import logging
import random
from collections import OrderedDict
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands

from config import config
from services.moderation import (
    DuplicateTracker,
    Level,
    classify,
    contains_family,
    contains_sexual,
    ensure_profanity,
    is_weak_reply,
    mirrors_insult,
    relevance_score,
    sanitize_reply,
)
from services.openrouter import BudgetExceeded, OpenRouterError
from services.prompts import build_messages, build_system_prompt

log = logging.getLogger("controlroom.chat")

_IST = timezone(timedelta(hours=5, minutes=30))


def _now_ist() -> str:
    return datetime.now(_IST).strftime("%A, %d %B %Y, %I:%M %p IST")


_FALLBACKS = [
    "ek sec bhai, thoda reload ho raha hai",
    "ruko ek second, dimaag sync kar raha hai",
    "chalo ek sec de do, net thoda der se connect hua",
]

_ROAST_NUDGE = (
    "You already said something too similar recently. Say it differently this time."
)

GAALI_INSTRUCTION = (
    "That message just abused/roasted you. Reply with a SAVAGE, witty 1-2 line "
    "Hinglish clapback that MUST contain a real desi gaali BIGGER and harder than "
    "theirs (eg chutiya, bkl, gandu, harami, lodu, madarchod - not a soft word). "
    "Do NOT mirror or echo them - never say 'tu bhi chutiya', 'teri X bhi Y', or "
    "copy their insult structure; invent a completely fresh punchline that attacks "
    "THEM. An emoji or two is welcome. "
    "Style like: 'chutiye, apni aukaat mein reh, yahan bakchodi mat kar 💀' or "
    "'bkl, teri himmat bhi kahan se aayi 😂'. "
    "If the same message also asks a genuine question, answer it briefly right after "
    "the comeback. "
    "HARD RULES: never mention their family or any relative, zero sexual content, "
    "do NOT tell them to calm down, do NOT say 'gaali mat do' / 'sambhal ja' / "
    "'behave karo' / 'let's keep it civil', do NOT lecture, deflect or moralise, "
    "and NEVER apologise. Just hit back harder."
)

GAALI_NUDGE = (
    "That reply was weak, preachy or a lazy echo - a real loser answer. Try again: "
    "actually curse them back with a proper BIG desi gaali and a sharp, ORIGINAL "
    "punchline (don't just repeat their words). No lecturing, no 'sambhal ja', no "
    "'gaali mat do', no calm-down crap, no family, no sexual stuff."
)

SEVERE_INSTRUCTION = (
    "They just used sexual and/or family-targeted abuse aimed at YOU. Destroy them "
    "with a SAVAGE but strictly NON-sexual, family-free comeback. Zero sexual "
    "content, zero flirting, zero innuendo, and NEVER mention their family or any "
    "relative - not even to insult. Do NOT mirror their words. Do NOT sound shocked, "
    "do NOT lecture, do NOT tell them to calm down or 'gaali mat do' - just verbally "
    "flatten them. Use a real BIG desi gaali (chutiya/bkl/gandu/harami/madarchod) "
    "and attack their trash talk and logic. One or two lines, sharp, funny and "
    "ruthless."
)

_AI_NOT_CONFIGURED = (
    "abhi mera AI brain set up nahi hua, admin ko bol OPENROUTER_API_KEY daale 🧠"
)


class ChatCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._duplicates = DuplicateTracker(window=10)
        self._handled: OrderedDict[int, float] = OrderedDict()
        bot.chat_cog = self

    def _already_handled(self, message_id: int) -> bool:
        return message_id in self._handled

    def _mark_handled(self, message_id: int) -> None:
        self._handled[message_id] = 1.0
        self._handled.move_to_end(message_id)
        while len(self._handled) > 5000:
            self._handled.popitem(last=False)

    @staticmethod
    def _strip_mention(content: str, bot_id: int) -> str:
        return content.replace(f"<@{bot_id}>", "").replace(f"<@!{bot_id}>", "").strip()

    async def _is_reply_to_bot(self, message: discord.Message) -> bool:
        ref = message.reference
        if ref is None or self.bot.user is None:
            return False
        resolved = ref.resolved
        if isinstance(resolved, discord.Message):
            return resolved.author.id == self.bot.user.id
        if ref.message_id:
            cached = getattr(self.bot, "_message_cache", None)
            if cached and cached.get(ref.message_id) == self.bot.user.id:
                return True
        return False

    def _channel_modes(self, channel_id: int, guild_id: int) -> tuple[bool, bool]:
        override = self.bot.memory.channel_override(channel_id)
        if override is not None:
            return override, override
        if not config.mentions_enabled:
            mentions = False
        elif config.ai_channel_ids:
            mentions = channel_id in config.ai_channel_ids
        else:
            mentions = True
        auto = channel_id in config.autonomous_channel_ids
        return mentions, auto

    async def _maybe_track(self, message: discord.Message) -> None:
        channel_id = message.channel.id
        if channel_id in config.blocked_channel_ids:
            return
        ai, auto = self._channel_modes(channel_id, message.guild.id)
        if not (ai or auto):
            return
        content = message.clean_content or message.content
        content = content[: config.max_input_length]
        await self.bot.memory.add_message(
            channel_id=channel_id,
            author_id=message.author.id,
            author_name=message.author.display_name,
            content=content,
            is_bot=False,
            guild_id=message.guild.id,
        )

    def _autonomous_worth_it(self, message: discord.Message) -> bool:
        if random.random() >= config.autonomous_probability:
            return False
        if relevance_score(message.content) < 0.3:
            return False

        recent = self.bot.memory.get_recent(message.channel.id, 8)
        if recent and recent[-1]["is_bot"]:
            return False
        if len(recent) < config.autonomous_min_messages:
            return False

        humans = [e for e in recent if not e["is_bot"]]
        two_human_chat = (
            len(humans) >= 2 and humans[-2]["author_id"] != humans[-1]["author_id"]
        )
        if two_human_chat:
            return random.random() < (config.autonomous_probability * 0.4)
        return True

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.guild is None:
            return
        if self.bot.user is None:
            return
        if message.author.bot or message.author.id == self.bot.user.id:
            return

        await self._maybe_track(message)

        if message.channel.id in config.blocked_channel_ids:
            return
        if self.bot.memory.get_bool_flag("kill_switch"):
            return
        if not self.bot.memory.guild_ai_enabled(message.guild.id):
            return

        mentions_enabled, auto_enabled = self._channel_modes(
            message.channel.id, message.guild.id
        )
        if not (mentions_enabled or auto_enabled):
            return

        body = self._strip_mention(message.content, self.bot.user.id)
        mentioned = self.bot.user in message.mentions
        is_reply = await self._is_reply_to_bot(message)
        direct = mentioned or is_reply
        if direct and not mentions_enabled:
            return
        if not direct and not auto_enabled:
            return
        if not body:
            return
        if self._already_handled(message.id):
            return

        classification = classify(body)

        if classification.blocked:
            if direct or mentioned:
                self._mark_handled(message.id)
                await self._send_blocked(message)
            return

        if direct and classification.wants_stop and not self.bot.memory.is_roast_optout(
            message.author.id
        ):
            await self.bot.memory.set_roast_optout(message.author.id, True)

        if not config.ai_configured:
            if direct and self.bot.failure_backoff.should_notify():
                self._mark_handled(message.id)
                await message.reply(
                    _AI_NOT_CONFIGURED,
                    mention_author=False,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            return

        limiter = self.bot.limiter
        if not limiter.global_ready() or not limiter.minute_ok():
            return
        if not self.bot.openrouter.budget_available():
            if direct and self.bot.failure_backoff.should_notify():
                self._mark_handled(message.id)
                await message.channel.send(
                    "aaj ka AI budget khatam ho gaya, kal aana 💀",
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            return

        if direct:
            kind = "direct"
        else:
            if not config.autonomous_enabled:
                return
            if not self.bot.memory.guild_autonomous_enabled(message.guild.id):
                return
            if not limiter.user_ready(message.author.id):
                return
            if not self._autonomous_worth_it(message):
                return
            kind = "auto"

        self._mark_handled(message.id)
        await self._respond(message, kind, classification)

    async def _build_context(self, message: discord.Message) -> list[dict]:
        context = self.bot.memory.get_recent(
            message.channel.id, config.context_messages
        )
        total = sum(len(e["content"]) + len(e["author_name"]) for e in context)
        while context and total > config.context_char_budget:
            dropped = context.pop(0)
            total -= len(dropped["content"]) + len(dropped["author_name"])
        if not context or context[-1]["author_id"] != message.author.id:
            context.append(
                {
                    "author_id": message.author.id,
                    "author_name": message.author.display_name,
                    "content": self._strip_mention(
                        message.clean_content or message.content,
                        self.bot.user.id,
                    )[: config.max_input_length],
                    "is_bot": False,
                }
            )
        return context

    async def _generate(
        self, message: discord.Message, context: list[dict], classification
    ) -> tuple[str, bool]:
        user_id = message.author.id
        pref_language = self.bot.memory.get_pref(user_id, "language")
        roast_optout = self.bot.memory.is_roast_optout(user_id)

        severe = bool(getattr(classification, "severe", False))
        need_gaali = (
            config.allow_profanity
            and not roast_optout
            and not classification.wants_stop
            and (severe or classification.level in (Level.BANTER, Level.ROAST))
        )
        extra_instructions: list[str] = []
        if severe:
            extra_instructions.append(SEVERE_INSTRUCTION)
        if need_gaali:
            extra_instructions.append(GAALI_INSTRUCTION)

        system_prompt = build_system_prompt(
            level=classification.level,
            language=classification.language,
            now=_now_ist(),
            roast_optout=roast_optout,
            pref_language=pref_language,
        )
        messages = build_messages(system_prompt, context)
        for instruction in extra_instructions:
            messages.append({"role": "user", "content": instruction})

        user_text = ""
        for entry in reversed(context):
            if not entry.get("is_bot"):
                user_text = entry.get("content", "")
                break

        reply = await self.bot.openrouter.complete(messages)
        reply = sanitize_reply(reply, config.max_reply_length)
        if not reply:
            retry = await self.bot.openrouter.complete(messages)
            reply = sanitize_reply(retry, config.max_reply_length)

        if need_gaali and reply and (
            is_weak_reply(reply) or mirrors_insult(user_text, reply)
        ):
            stronger = build_messages(system_prompt + "\n" + GAALI_NUDGE, context)
            for instruction in extra_instructions:
                stronger.append({"role": "user", "content": instruction})
            second = await self.bot.openrouter.complete(stronger)
            second = sanitize_reply(second, config.max_reply_length)
            if second and not is_weak_reply(second) and not mirrors_insult(
                user_text, second
            ):
                reply = second
            else:
                reply = ensure_profanity("", lang=classification.language)

        if not reply:
            return "", False

        if need_gaali and (contains_family(reply) or contains_sexual(reply)):
            log.info("Replacing reply that touched family/sexual content.")
            reply = ensure_profanity("", lang=classification.language)

        if self._duplicates.is_duplicate(reply):
            retry_messages = build_messages(
                system_prompt + "\n" + _ROAST_NUDGE, context
            )
            for instruction in extra_instructions:
                retry_messages.append({"role": "user", "content": instruction})
            retry = await self.bot.openrouter.complete(retry_messages)
            retry = sanitize_reply(retry, config.max_reply_length)
            if need_gaali and retry and (
                is_weak_reply(retry) or mirrors_insult(user_text, retry)
            ):
                retry = ensure_profanity("", lang=classification.language)
            if retry and not self._duplicates.is_duplicate(retry):
                return retry, False
            return reply, True

        return reply, False

    def _failure_reply(self, classification, user_id: int) -> str:
        roast_optout = self.bot.memory.is_roast_optout(user_id)
        clapback = (
            config.allow_profanity
            and not roast_optout
            and not classification.wants_stop
            and (
                getattr(classification, "severe", False)
                or classification.level in (Level.BANTER, Level.ROAST)
            )
        )
        if clapback:
            return ensure_profanity("", lang=classification.language)
        return random.choice(_FALLBACKS)

    async def _respond(
        self, message: discord.Message, kind: str, classification
    ) -> None:
        context = await self._build_context(message)
        try:
            async with message.channel.typing():
                reply, is_dup = await self._generate(message, context, classification)
        except BudgetExceeded:
            log.warning("Daily budget reached while responding; skipping.")
            return
        except OpenRouterError as exc:
            log.error("AI request failed: %s", exc)
            if kind == "direct":
                try:
                    await message.channel.send(
                        self._failure_reply(classification, message.author.id),
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                except discord.HTTPException:
                    pass
            return

        if not reply:
            if kind == "direct":
                try:
                    await message.channel.send(
                        self._failure_reply(classification, message.author.id),
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                except discord.HTTPException:
                    pass
            return
        if is_dup:
            return

        allowed = discord.AllowedMentions.none()
        try:
            if kind == "direct":
                sent = await message.reply(
                    reply, mention_author=False, allowed_mentions=allowed
                )
            else:
                sent = await message.channel.send(reply, allowed_mentions=allowed)
        except discord.HTTPException as exc:
            log.warning("Failed to send message: %s", exc.__class__.__name__)
            return

        self._duplicates.add(reply)
        self.bot.limiter.register(message.author.id if kind == "auto" else None)
        self.bot.limiter.prune_users()
        await self.bot.memory.add_message(
            channel_id=message.channel.id,
            author_id=self.bot.user.id,
            author_name=self.bot.user.display_name,
            content=reply,
            is_bot=True,
            guild_id=message.guild.id,
        )
        remember = getattr(self.bot, "remember_message", None)
        if remember is not None:
            remember(sent.id, self.bot.user.id)

    async def _send_blocked(self, message: discord.Message) -> None:
        await message.reply(
            "yeh topic mere paygrade se bahar hai, chill karo 😅",
            mention_author=False,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @app_commands.command(name="bothelp", description="Show what this bot can do.")
    async def bothelp(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title="Echo",
            description="Ek funny, chill AI member. Koi command zaroori nahi - "
            "bas mujhe @mention karke baat karo, main reply kar dunga.",
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="@Echo <message>",
            value="Main trigger hone ka asli tareeka. koi slash command nahi chahiye.",
            inline=False,
        )
        embed.add_field(
            name="/ai on | off",
            value="Is channel mein AI replies on/off (admins).",
            inline=False,
        )
        embed.add_field(
            name="/ai status",
            value="Current config dekho (admins).",
            inline=False,
        )
        embed.add_field(
            name="/ai clear",
            value="Apni conversation memory clear karo.",
            inline=False,
        )
        embed.add_field(
            name="/ai autochat <on|off>",
            value="Spontaneous participation on/off (admins).",
            inline=False,
        )
        embed.add_field(
            name="/ai kill <on|off>",
            value="Sab AI replies turant band karo (admins).",
            inline=False,
        )
        embed.set_footer(text="Mention karo ya reply karo, main aa jaunga.")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ChatCog(bot))
