# Menace — Discord Chat Bot

A funny, human-like AI Discord community member named **Menace** for **Control Room**. The bot speaks natural Hinglish/Hindi/English, has adaptive humour, playful profanity in friendly banter, intelligent context-aware roasting, and strong guardrails (serious chat detection, kill switch, cost/budget controls, admin-only settings).

This is a fully working implementation built with `discord.py` 2.x, `aiohttp`, `python-dotenv` and SQLite.

---

## 1. Project Structure

```text
control-room-ai/
├── bot.py              # Bot entrypoint (intents, setup, sync, shutdown)
├── config.py           # Central config: loads .env + validation + helpers
├── requirements.txt    # Python dependencies
├── render.yaml         # Render Blueprint (background worker)
├── Procfile            # Process definition for hosts that use one
├── .python-version     # Pinned Python version for hosts
├── .env.example        # Placeholder environment variables
├── .gitignore          # Ignore secrets, caches, local data
├── README.md           # This file
├── cogs/
│   ├── __init__.py
│   ├── chat.py         # Conversation logic: mentions, context, roasts
│   └── admin.py        # Admin controls: /ai on|off|status|clear|autochat|kill
├── services/
│   ├── __init__.py
│   ├── moderation.py   # Tone/language classification, duplicate detection, sanitisation
│   ├── memory.py       # Bounded per-channel history, prefs, opt-out, guild/channel flags
│   ├── openrouter.py    # Async OpenRouter client: retries, 429/backoff, budget, timeouts
│   ├── prompts.py       # Persona/system prompt builder + message formatter
│   └── runtime.py      # Rate limits (user/global/minute), failure backoff
├── tests/
│   └── test_smoke.py   # Offline smoke tests (no network required)
└── data/
    └── .gitkeep        # SQLite DB goes here (ignored by git)
```

---

## 2. Prerequisites

- Python **3.11+** (3.13.x is fine)
- A Discord account with permission to create an application/bot
- An [OpenRouter](https://www.openrouter.ai/) account with API credits
- Access to your Discord server **Control Room** (where you'll add the bot)

---

## 3. Create a Discord Application and Bot

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications).
2. Click **New Application** → give it a name (e.g. `Control Room AI`).
3. Go to **Bot** in the sidebar → click **Add Bot**.
4. Under **Token**, click **Reset Token** (if first time) and **Copy** it. Keep this safe.
5. Under **Privileged Gateway Intents**, enable **Message Content Intent**.
6. Save changes.

> Note: Message Content Intent is required to read message text for mentions, replies and spontaneous participation. Without it, the bot can only respond to slash commands and direct mentions in very limited cases. If your bot is in >100 servers this requires Discord verification; for a private/server-specific bot it's usually fine.

---

## 4. Invite the Bot with Correct Permissions

1. Go to **OAuth2 → URL Generator** in the Developer Portal.
2. Scopes: select `bot`, `applications.commands`.
3. Bot Permissions (recommended minimum for safe operation):
   - `Send Messages`
   - `Embed Links`
   - `Read Message History`
   - `View Channels`
   - `Use Slash Commands`
   - `Attach Files` (optional, not used)
4. Copy the generated URL and open it in your browser.
5. Select your server **Control Room** and authorise the bot.

---

## 5. Get OpenRouter API Key and Choose a Model

1. Sign in to [OpenRouter](https://www.openrouter.ai/).
2. Go to [Keys](https://www.openrouter.ai/keys) → create a new API key.
3. (Optional but recommended) Set usage limits / per-key restrictions.
4. Choose a model from [OpenRouter Models](https://www.openrouter.ai/models). Any general chat model works. The example uses `openai/gpt-4o-mini` which is cheap and fast. You can change this anytime via `.env`.

> Never share your OpenRouter key or Discord token. They are secrets and must stay in `.env` only.

---

## 6. Setup the Project (Windows)

Open PowerShell in the project directory (e.g. `C:\Users\HP\Desktop\chat-bot\control-room-ai\`).

### 6.1 Create and activate a virtual environment (recommended)

```powershell
# Create venv
python -m venv .venv

# Activate (Windows)
.\.venv\Scripts\Activate.ps1

# If PowerShell blocks scripts, run:
# Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

### 6.2 Install dependencies

```powershell
pip install -r requirements.txt
```

### 6.3 Configure environment

```powershell
# Copy example to real .env
Copy-Item .env.example .env
```

Edit `.env` with a text editor (e.g. VS Code, Notepad++). Fill in at minimum:

```env
DISCORD_BOT_TOKEN=your-discord-bot-token-here
OPENROUTER_API_KEY=sk-or-v1-your-openrouter-key-here
OPENROUTER_MODEL=openai/gpt-4o-mini
```

Optional but useful:

- `DEV_GUILD_ID` — if you set this, slash commands sync instantly to that guild only (great for testing). Leave 0 for global sync (can take up to 1 hour).
- `MENTION_REPLIES_ENABLED` — default `true`. When on, `@Menace <message>` gets an automatic reply in any non-blocked channel.
- `AI_CHANNEL_IDS` — optional allowlist. Leave empty to allow mentions in **all** channels; if set, mentions only work in the listed channels.
- `AUTONOMOUS_CHANNEL_IDS` — channels where the bot may also jump in **without** being mentioned. Empty = fully disabled.
- `BLOCKED_CHANNEL_IDS` — channels the bot must never interact in.
- `AUTONOMOUS_ENABLED` — master switch for normal-message (non-mention) replies. Default `false`.
- `ALLOW_PROFANITY` — default `true`. When on, MENACE curses back (gaali) when abused/roasted, and replies are guaranteed to include a gaali if the model softens. Set `false` to keep it clean. If someone asks it to stop roasting them, that person is opted out automatically.
- `AUTONOMOUS_PROBABILITY` — default 0.08 (8% chance to jump in when autonomous is enabled).
- `DAILY_REQUEST_BUDGET` — default 600. When reached, bot stops making AI calls gracefully.
- `ADMIN_USER_IDS` / `ADMIN_ROLE_IDS` — users/roles allowed to change server-wide settings.

To get channel IDs: enable Developer Mode in Discord (User Settings → Advanced → Developer Mode), then right-click a channel → Copy ID.

---

## 7. Run the Bot

With venv activated and `.env` configured:

```powershell
python bot.py
```

You should see logs like:

```text
18:12:34 | INFO    | controlroom.openrouter | ...
18:12:34 | INFO    | controlroom | Loaded extension cogs.chat
18:12:34 | INFO    | controlroom | Loaded extension cogs.admin
18:12:34 | INFO    | controlroom | Synced N commands globally (or to dev guild)
18:12:34 | INFO    | controlroom | Logged in as Control Room AI (id=...)
18:12:34 | INFO    | controlroom | Serving 1 guild(s).
```

If you see configuration errors, fix `.env` as instructed.

---

## 8. Commands

There is **no roast command** — roasting and gaali replies happen automatically through mentions. The remaining commands are only for help and admin/config.

| Command | Who | Description |
|---|---|---|
| `/bothelp` | Anyone | Show how to use the bot and the admin commands. |
| `/ai on` | Admin/Manage Guild | Enable AI replies in the current channel (overrides config defaults). |
| `/ai off` | Admin/Manage Guild | Disable AI replies in the current channel. |
| `/ai status` | Admin/Manage Guild | Show model, kill switch, per-channel/guild state, budget usage, cooldowns. |
| `/ai clear` | Anyone | Clear your stored conversational memory (messages + prefs). |
| `/ai autochat <on\|off>` | Admin/Manage Guild | Toggle spontaneous (autonomous) participation for the entire server. |
| `/ai kill <on\|off>` | Admin/Manage Guild | Global kill switch — instantly stops all AI replies. Great for emergencies. |

Notes:
- **No commands needed**: just `@Menace <your message>` in any permitted channel and it replies automatically.
- The bot reads the recent channel context and the tone of your message, then answers in kind (greeting, casual chat, witty comeback, savage roast, genuine help, or calm/supportive if the topic is serious).
- **Gaali / roast back**: if you abuse, taunt or roast MENACE, it fires back with its own gaali/roast (guaranteed to include a gaali when `ALLOW_PROFANITY=true`).
- Replies reference your triggering message.
- Normal-message (non-mention) replies are **off by default**; enable them per server with `/ai autochat on` and per channel with `AUTONOMOUS_CHANNEL_IDS`.
- The bot never replies to other bots or itself, won't answer the same message twice, and won't roast someone who is genuinely asking for help.
- Blocked channels are completely ignored.
- If someone asks to stop roasting them, the bot opts out for that person automatically and permanently. If someone is genuinely upset, it drops the jokes.

---

## 9. Behaviour & Personality Notes

- **Language mixing**: Hinglish/Hindi/English; matches speaker's vibe.
- **Banter / clap-back**: if someone curses, taunts or roasts MENACE, it fires back with its own gaali/roast in the same language and energy (a notch sharper), but never escalates to credible threats or hate, and never drags in family or protected traits.
- **Roast mode**: triggered automatically by "roast me" style messages (no command). Creative and personalised, not cruel.
- **Serious mode**: detects distress/self-harm cues and drops jokes; stays calm and supportive.
- **Memory**: short-term, bounded (per-channel ring buffer + SQLite). Only minimal context sent to OpenRouter.
- **Anti-spam/cost**: per-user cooldown, global cooldown, per-minute cap, daily budget, duplicate detection, length caps.
- **No identity dump**: doesn't call itself "an AI" unless directly asked; avoids generic chatbot phrases.

---

## 10. Troubleshooting

| Issue | Possible Cause | Fix |
|---|---|---|
| `Configuration error: DISCORD_BOT_TOKEN is missing` | `.env` not loaded or empty | Ensure `.env` exists in project root and has correct values. |
| `OPENROUTER_API_KEY is missing` | Missing key | Add `sk-or-v1-...` to `.env`. |
| Slash commands don't appear | Global sync delay | Set `DEV_GUILD_ID` to your server ID for instant sync. Or wait up to ~1 hour globally. |
| Bot doesn't respond to messages | Message Content Intent disabled | Enable **Message Content Intent** in Developer Portal (Bot → Privileged Gateway Intents). Restart bot. |
| Bot doesn't respond in channel | Channel not allowed | Use `/ai status` (admin) or add channel ID to `AI_CHANNEL_IDS`/`AUTONOMOUS_CHANNEL_IDS`. Check `BLOCKED_CHANNEL_IDS`. |
| Rate limited (429) | Too many requests | Bot already retries with backoff. Consider increasing cooldowns or budget if persistent. |
| Timeout/network errors | Slow/OpenRouter issue | Check internet; try different model. Bot falls back to a short offline message on direct queries if budget ok but API fails. |
| SQLite errors on start | Permission/path issue | Ensure `data/` exists and is writable. The bot auto-creates `memory.sqlite3`. |
| Commands fail with "Missing Permissions" | Inviting without correct scopes/permissions | Reinvite with `applications.commands` scope and required bot permissions. |
| Autocomplete/ephemeral messages not working | Interaction expired | Commands respond quickly; retry if the network was slow. |

---

## 11. Security & Privacy

- **Secrets**: read only from `.env`. Never committed. `.gitignore` excludes `.env`, `__pycache__/`, `data/*.sqlite3`, logs.
- **No credential leakage**: logs never print tokens/keys. HTTP errors are sanitised.
- **Bounded memory**: history capped per channel; old messages dropped. `clear_user_all` wipes a user's messages and prefs.
- **Roast opt-out**: per-user flag set automatically when someone asks MENACE to stop, and respected by the persona.
- **Hard blocks**: threats, hate, doxxing patterns blocked before sending to AI.
- **Budget + kill switch**: guardrails against runaway cost/abuse.

---

## 12. Development Notes

- All I/O to OpenRouter/DB is async (non-blocking). Discord event loop never blocked.
- `moderation` is heuristic (tweakable) — it guides tone, doesn't replace provider safety.
- `memory` uses in-memory buffers for speed + SQLite for persistence.
- `prompts` keep context minimal (only last N messages + names).
- `bot.py` remembers bot messages in a tiny LRU cache to detect replies reliably.
- `admin.py` uses role/user allowlists from config; also respects Manage Guild/Channels as fallback.

---

## 13. Running Tests (Smoke)

From the project root with the venv active:

```powershell
python tests\test_smoke.py
```

Expected: `ALL SMOKE TESTS PASSED`. This runs fully offline: it sets dummy env
vars and does not connect to Discord or OpenRouter. It covers tone/language
classification (greetings, Hinglish, gaali banter, roast requests, coding-help
questions, serious messages), mention-by-default channel logic, message
de-duplication, prompts, memory and rate limiting.

---

## 14. Deploying on Render

This project ships a Render Blueprint (`render.yaml`) configured as a
**Background Worker** (it needs a long-running process, not a web server).

1. Push the project to a Git repository (GitHub/GitLab).
2. In Render: **New +** → **Blueprint** → select the repo. If the bot lives in a
   subfolder, set the Blueprint path / **Root Directory** to `control-room-ai`.
3. Render reads `render.yaml`. Set the secret env vars when prompted:
   - `DISCORD_BOT_TOKEN`
   - `OPENROUTER_API_KEY`
   - optionally `OPENROUTER_MODEL`
4. Deploy. The worker runs `python bot.py` and keeps running.

If you prefer a manual setup instead of the Blueprint:
- Create **New +** → **Background Worker**.
- Build command: `pip install -r requirements.txt`
- Start command: `python bot.py`
- Add the env vars from `.env.example`.

Notes:
- The `data/` SQLite file lives on the worker's ephemeral disk; that's fine
  because conversation memory is a bounded, short-term cache. Add a Render Disk
  if you want it to survive restarts.
- **Discord Developer Portal → Bot → Privileged Gateway Intents → Message
  Content Intent must be ON.** Deployed bots with the intent off cannot read
  mentions and will appear dead.
- Ensure the bot was invited with the `bot` + `applications.commands` scopes and
  at least View Channels / Send Messages / Read Message History permissions.
- Tokens/keys are only read from env vars and are never logged.

---

## 15. Production Tips

- Use a process manager (e.g. PM2, NSSM, systemd) to auto-restart on crash.
- Keep `OPENROUTER_MAX_TOKENS` small (default 220) to control cost.
- Tune `AUTONOMOUS_PROBABILITY` to fit your server's activity.
- Review logs occasionally; set `LOG_CHANNEL_ID` in future if you want alerts.
- Rotate API keys periodically.

---

## Final Notes

This bot is designed to feel like "that one funny friend" in Control Room: casual, chaotic in a fun way, affectionate with jabs, and decent when it matters. No TODOs/pseudocode remain; code compiles and smoke tests pass. Enjoy!