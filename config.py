from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

load_dotenv(BASE_DIR / ".env", override=False)


def _str(name: str, default: str = "") -> str:
    value = os.getenv(name)
    return value.strip() if value is not None else default


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(float(raw.strip()))
    except ValueError:
        return default


def _float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw.strip())
    except ValueError:
        return default


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _int_list(name: str) -> list[int]:
    raw = os.getenv(name, "")
    out: list[int] = []
    for part in raw.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(part))
        except ValueError:
            continue
    return out


def _str_list(name: str) -> list[str]:
    raw = os.getenv(name, "")
    return [p.strip() for p in raw.replace(";", ",").split(",") if p.strip()]


@dataclass(frozen=True)
class Config:
    discord_token: str = field(default_factory=lambda: _str("DISCORD_BOT_TOKEN"))
    openrouter_api_key: str = field(default_factory=lambda: _str("OPENROUTER_API_KEY"))
    openrouter_model: str = field(
        default_factory=lambda: _str(
            "OPENROUTER_MODEL", "claude-haiku-5.5:free"
        )
    )
    openrouter_fallback_models: tuple[str, ...] = field(
        default_factory=lambda: (
            tuple(_str_list("OPENROUTER_FALLBACK_MODELS"))
            if "OPENROUTER_FALLBACK_MODELS" in os.environ
            else ("mimo-v2.6-flash:free",)
        )
    )

    openrouter_base_url: str = field(
        default_factory=lambda: _str(
            "OPENROUTER_BASE_URL", "https://tokenharbor.ai/v1"
        )
    )
    openrouter_app_name: str = field(
        default_factory=lambda: _str("OPENROUTER_APP_NAME", "Echo")
    )
    openrouter_app_url: str = field(
        default_factory=lambda: _str("OPENROUTER_APP_URL", "")
    )
    temperature: float = field(
        default_factory=lambda: _float("OPENROUTER_TEMPERATURE", 0.92)
    )
    max_tokens: int = field(
        default_factory=lambda: _int("OPENROUTER_MAX_TOKENS", 160)
    )
    request_timeout: float = field(
        default_factory=lambda: _float("OPENROUTER_TIMEOUT", 30.0)
    )
    max_retries: int = field(
        default_factory=lambda: _int("OPENROUTER_MAX_RETRIES", 2)
    )

    # Optional secondary provider (e.g. OpenRouter). When the primary provider
    # is rate limited or errors out, the bot retries here automatically.
    openrouter_secondary_base_url: str = field(
        default_factory=lambda: _str("OPENROUTER_SECONDARY_BASE_URL")
    )
    openrouter_secondary_api_key: str = field(
        default_factory=lambda: _str("OPENROUTER_SECONDARY_API_KEY")
    )
    openrouter_secondary_models: tuple[str, ...] = field(
        default_factory=lambda: tuple(_str_list("OPENROUTER_SECONDARY_MODELS"))
    )

    allow_profanity: bool = field(
        default_factory=lambda: _bool("ALLOW_PROFANITY", True)
    )

    mentions_enabled: bool = field(
        default_factory=lambda: _bool("MENTION_REPLIES_ENABLED", True)
    )
    ai_channel_ids: list[int] = field(
        default_factory=lambda: _int_list("AI_CHANNEL_IDS")
    )
    autonomous_channel_ids: list[int] = field(
        default_factory=lambda: _int_list("AUTONOMOUS_CHANNEL_IDS")
    )
    blocked_channel_ids: list[int] = field(
        default_factory=lambda: _int_list("BLOCKED_CHANNEL_IDS")
    )
    autonomous_enabled: bool = field(
        default_factory=lambda: _bool("AUTONOMOUS_ENABLED", False)
    )
    autonomous_probability: float = field(
        default_factory=lambda: _float("AUTONOMOUS_PROBABILITY", 0.08)
    )
    autonomous_min_messages: int = field(
        default_factory=lambda: _int("AUTONOMOUS_MIN_MESSAGES", 3)
    )

    user_cooldown: float = field(
        default_factory=lambda: _float("USER_COOLDOWN_SECONDS", 20.0)
    )
    global_cooldown: float = field(
        default_factory=lambda: _float("GLOBAL_COOLDOWN_SECONDS", 4.0)
    )
    max_responses_per_minute: int = field(
        default_factory=lambda: _int("MAX_RESPONSES_PER_MINUTE", 8)
    )
    daily_request_budget: int = field(
        default_factory=lambda: _int("DAILY_REQUEST_BUDGET", 600)
    )

    context_messages: int = field(
        default_factory=lambda: _int("CONTEXT_MESSAGES", 12)
    )
    context_char_budget: int = field(
        default_factory=lambda: _int("CONTEXT_CHAR_BUDGET", 6000)
    )
    max_input_length: int = field(
        default_factory=lambda: _int("MAX_INPUT_LENGTH", 1200)
    )
    max_reply_length: int = field(
        default_factory=lambda: _int("MAX_REPLY_LENGTH", 360)
    )
    per_channel_history_cap: int = field(
        default_factory=lambda: _int("PER_CHANNEL_HISTORY_CAP", 60)
    )

    admin_role_ids: list[int] = field(
        default_factory=lambda: _int_list("ADMIN_ROLE_IDS")
    )
    admin_user_ids: list[int] = field(
        default_factory=lambda: _int_list("ADMIN_USER_IDS")
    )
    log_channel_id: int = field(
        default_factory=lambda: _int("LOG_CHANNEL_ID", 0)
    )

    dev_guild_id: int = field(default_factory=lambda: _int("DEV_GUILD_ID", 0))

    # Voice / audio playback
    voice_enabled: bool = field(
        default_factory=lambda: _bool("VOICE_ENABLED", True)
    )
    audio_folder: str = field(
        default_factory=lambda: _str("AUDIO_FOLDER", "audio")
    )
    ffmpeg_executable: str = field(
        default_factory=lambda: _str("FFMPEG_EXECUTABLE", "ffmpeg")
    )

    database_url: str = field(default_factory=lambda: _str("DATABASE_URL"))
    pg_host: str = field(default_factory=lambda: _str("PGHOST", "localhost"))
    pg_port: int = field(default_factory=lambda: _int("PGPORT", 5432))
    pg_user: str = field(default_factory=lambda: _str("PGUSER", "postgres"))
    pg_password: str = field(default_factory=lambda: _str("PGPASSWORD"))
    pg_database: str = field(
        default_factory=lambda: _str("PGDATABASE", "discord-chatbot-ai")
    )

    @property
    def ai_configured(self) -> bool:
        return bool(self.openrouter_api_key and self.openrouter_model)

    @property
    def secondary_configured(self) -> bool:
        return bool(
            self.openrouter_secondary_base_url
            and self.openrouter_secondary_api_key
            and self.openrouter_secondary_models
        )

    @property
    def db_configured(self) -> bool:
        return bool(self.database_url or self.pg_password)

    @property
    def audio_dir(self) -> Path:
        path = Path(self.audio_folder)
        return path if path.is_absolute() else (BASE_DIR / path)

    def is_admin(self, user_id: int, role_ids: list[int] | None = None) -> bool:
        if user_id in self.admin_user_ids:
            return True
        if role_ids:
            return any(rid in self.admin_role_ids for rid in role_ids)
        return False

    def fatal_problems(self) -> list[str]:
        problems: list[str] = []
        if not self.discord_token:
            problems.append("DISCORD_BOT_TOKEN is missing.")
        return problems

    def warnings(self) -> list[str]:
        problems: list[str] = []
        if not self.openrouter_api_key:
            problems.append(
                "OPENROUTER_API_KEY is missing - AI replies are disabled until "
                "it is set."
            )
        if not self.openrouter_model:
            problems.append("OPENROUTER_MODEL is missing.")
        if not 0.0 <= self.autonomous_probability <= 1.0:
            problems.append("AUTONOMOUS_PROBABILITY must be between 0 and 1.")
        if self.max_tokens <= 0:
            problems.append("OPENROUTER_MAX_TOKENS must be positive.")
        if not self.db_configured:
            problems.append(
                "PostgreSQL is not configured - memory persistence is disabled "
                "until DATABASE_URL or PGPASSWORD is set."
            )
        return problems

    def validate(self) -> list[str]:
        return self.fatal_problems() + self.warnings()


config = Config()
