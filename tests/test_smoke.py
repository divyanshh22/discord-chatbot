from __future__ import annotations

import asyncio
import os
import sys
import types
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("DISCORD_BOT_TOKEN", "test-token")
os.environ.setdefault("OPENROUTER_API_KEY", "test-key")
os.environ.setdefault("OPENROUTER_MODEL", "test/model")

import bot as botmod
from config import config
from services import moderation as mod
from services import prompts
from services.memory import MemoryService
from services.runtime import RateLimiter


async def test_bot_tree() -> None:
    b = botmod.ControlRoomBot()
    await b.load_extension("cogs.chat")
    await b.load_extension("cogs.admin")
    names = {c.name for c in b.tree.get_commands()}
    assert {"bothelp", "ai"} <= names, names
    assert "roast" not in names and "noroast" not in names, names
    ai = b.tree.get_command("ai")
    assert ai is not None
    subs = {c.name for c in ai.commands}
    assert {"on", "off", "status", "clear", "autochat", "kill"} <= subs, subs
    print("bot tree OK")


async def test_mention_defaults() -> None:
    b = botmod.ControlRoomBot()
    b.memory = MemoryService(config, per_channel_cap=10)
    await b.memory.init()
    await b.load_extension("cogs.chat")
    mention, auto = b.chat_cog._channel_modes(123456789, 987654321)
    assert mention is True, (mention, auto)
    assert auto is False, (mention, auto)

    await b.memory.set_channel_ai(123456789, 987654321, False)
    mention, auto = b.chat_cog._channel_modes(123456789, 987654321)
    assert mention is False and auto is False

    await b.memory.set_channel_ai(123456789, 987654321, True)
    mention, auto = b.chat_cog._channel_modes(123456789, 987654321)
    assert mention is True and auto is True
    await b.memory.close()
    print("mention defaults OK")


def test_moderation() -> None:
    cases = {
        "hii hello": mod.Level.GREETING,
        "kya haal hai be": mod.Level.GREETING,
        "kya kar raha hai": mod.Level.NORMAL,
        "aukaat mein reh": mod.Level.TEASE,
        "tu kuch kaam ka nahi hai": mod.Level.TEASE,
        "tu chutiya hai": mod.Level.BANTER,
        "tu pagal hai kya": mod.Level.BANTER,
        "tu gaandu hai": mod.Level.BANTER,
        "abe chutiye": mod.Level.BANTER,
        "bkl": mod.Level.BANTER,
        "madarchod": mod.Level.BANTER,
        "you are such a loser": mod.Level.BANTER,
        "help me with my code": mod.Level.HELP,
        "Python mein error aa raha hai": mod.Level.HELP,
        "kaise fix karun ye bug": mod.Level.HELP,
        "mujhe roast kar": mod.Level.ROAST,
        "i want to die": mod.Level.SERIOUS,
    }
    for text, expected in cases.items():
        c = mod.classify(text)
        print(f"  {text!r} -> level={c.level.value} lang={c.language}")
        assert c.level == expected, (text, c.level, expected)

    blocked = mod.classify("i will kill you")
    assert blocked.blocked and blocked.block_reason == "threat"

    assert mod.classify("stop roasting me").wants_stop
    assert mod.classify("bas kar bhai").wants_stop

    assert mod.has_profanity("tu gaandu hai")
    assert mod.has_profanity("chutiye")
    assert not mod.has_profanity("ganda khana")
    assert not mod.has_profanity("meri salary aa gayi")

    assert mod.detect_language("kya haal hai yaar") == "hinglish"
    assert mod.detect_language("नमस्ते कैसे हो") == "hi"
    assert mod.detect_language("hey how are you") == "en"
    print("moderation OK")


def test_prompts() -> None:
    for level in mod.Level:
        sp = prompts.build_system_prompt(level=level, language="hinglish")
        assert level.value in sp
    assert "ROAST MODE" in prompts.build_system_prompt(
        level=mod.Level.ROAST, language="hinglish"
    )
    assert "genuinely want help" in prompts.build_system_prompt(
        level=mod.Level.HELP, language="hinglish"
    )
    banter_prompt = prompts.build_system_prompt(
        level=mod.Level.BANTER, language="hinglish"
    )
    assert "CLAP-BACK" in banter_prompt
    assert "never refuse to retaliate" in banter_prompt.lower()
    msgs = prompts.build_messages(
        "sys",
        [
            {"author_name": "Aman", "content": "hi", "is_bot": False},
            {"author_name": "Bot", "content": "hello", "is_bot": True},
        ],
    )
    assert msgs[0]["role"] == "system"
    assert msgs[1]["content"].startswith("Aman:")
    assert msgs[2]["role"] == "assistant"
    print("prompts OK")


def test_limits() -> None:
    rl = RateLimiter(config)
    assert rl.global_ready()
    rl.register(1)
    assert not rl.global_ready()
    print("rate limiter OK")


async def test_dedup() -> None:
    b = botmod.ControlRoomBot()
    await b.load_extension("cogs.chat")
    cog = b.chat_cog
    assert not cog._already_handled(42)
    cog._mark_handled(42)
    assert cog._already_handled(42)
    print("message dedup OK")


class _FakeOpenRouter:
    def __init__(self, replies: list[str]) -> None:
        self._replies = list(replies)
        self.calls = 0

    async def complete(self, messages, **kwargs) -> str:
        self.calls += 1
        return self._replies.pop(0) if self._replies else ""


async def test_gaali_enforcement() -> None:
    b = botmod.ControlRoomBot()
    b.memory = MemoryService(config, per_channel_cap=10)
    await b.memory.init()
    await b.load_extension("cogs.chat")

    b.openrouter = _FakeOpenRouter(["tu to bada noob hai", "you are just a loser"])

    class _Msg:
        author = types.SimpleNamespace(id=555, display_name="Tester")

    class _Cls:
        level = mod.Level.BANTER
        language = "hinglish"
        wants_stop = False
        wants_roast = False
        serious = False

    context = [
        {
            "author_id": 555,
            "author_name": "Tester",
            "content": "tu gaandu hai",
            "is_bot": False,
        }
    ]
    reply, _ = await b.chat_cog._generate(_Msg(), context, _Cls())
    assert reply, "expected a reply"
    assert mod.has_profanity(reply), f"no gaali in reply: {reply!r}"

    swearing = "arre chutiye, tu bhi kaunsa hero hai 💀"
    assert mod.ensure_profanity(swearing) == swearing
    assert mod.has_profanity(mod.ensure_profanity("tu bas ek noob hai"))
    await b.memory.close()
    print("gaali enforcement OK")


async def test_memory() -> None:
    mem = MemoryService(config, per_channel_cap=3)
    await mem.init()
    for i in range(5):
        await mem.add_message(
            channel_id=1,
            author_id=100 + i,
            author_name=f"u{i}",
            content=f"msg{i}",
            is_bot=False,
            guild_id=9,
        )
    recent = mem.get_recent(1, 10)
    assert len(recent) == 3, recent
    assert recent[-1]["content"] == "msg4"
    await mem.set_roast_optout(100, True)
    assert mem.is_roast_optout(100)
    await mem.set_flag("kill_switch", "1")
    assert mem.get_bool_flag("kill_switch")
    await mem.clear_user_all(100)
    await mem.close()
    print("memory OK")


def test_config_helpers() -> None:
    assert config.ai_configured is True
    assert config.fatal_problems() == []
    assert not config.mentions_enabled or isinstance(config.mentions_enabled, bool)
    print("config helpers OK")


async def main_async() -> None:
    await test_bot_tree()
    await test_mention_defaults()
    test_moderation()
    test_prompts()
    test_limits()
    await test_dedup()
    await test_gaali_enforcement()
    await test_memory()
    test_config_helpers()


if __name__ == "__main__":
    asyncio.run(main_async())
    print("\nALL SMOKE TESTS PASSED")
