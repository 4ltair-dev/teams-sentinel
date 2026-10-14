"""Configuration module for Teams Sentinel."""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
from dotenv import load_dotenv

# Base project directory
BASE_DIR = Path(__file__).resolve().parent

# Load .env file
load_dotenv(BASE_DIR / ".env")


def _get_list_from_env(key: str, default: List[str]) -> List[str]:
    raw = os.getenv(key)
    if not raw:
        return default
    return [item.strip().lower() for item in raw.split(",") if item.strip()]


@dataclass
class Config:
    # Telegram credentials
    telegram_bot_token: str = field(
        default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    )
    telegram_user_id: Optional[int] = field(
        default_factory=lambda: (
            int(os.getenv("TELEGRAM_USER_ID").strip())
            if os.getenv("TELEGRAM_USER_ID", "").strip().isdigit()
            else None
        )
    )

    # Gemini API credentials & model
    gemini_api_key: str = field(
        default_factory=lambda: os.getenv("GEMINI_API_KEY", "").strip()
    )
    gemini_model: str = field(
        default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-2.5-flash").strip()
    )

    # Audio & STT settings
    audio_device_index: Optional[int] = field(
        default_factory=lambda: (
            int(os.getenv("AUDIO_DEVICE_INDEX").strip())
            if os.getenv("AUDIO_DEVICE_INDEX", "").strip().lstrip("-").isdigit()
            and int(os.getenv("AUDIO_DEVICE_INDEX").strip()) >= 0
            else None
        )
    )
    audio_monitor_source: Optional[str] = field(
        default_factory=lambda: os.getenv("AUDIO_MONITOR_SOURCE", "").strip() or None
    )
    record_context_seconds: int = field(
        default_factory=lambda: int(os.getenv("RECORD_CONTEXT_SECONDS", "7").strip())
    )
    trigger_words: List[str] = field(
        default_factory=lambda: _get_list_from_env(
            "TRIGGER_WORDS",
            ["альтаир", "альтаира", "аскаров", "аскарова"],
        )
    )
    vosk_model_path: Path = field(
        default_factory=lambda: (
            Path(os.getenv("VOSK_MODEL_PATH", "model")).resolve()
            if os.getenv("VOSK_MODEL_PATH")
            else BASE_DIR / "model"
        )
    )

    # Cooldown seconds after alert to prevent repeated triggers
    cooldown_seconds: int = field(
        default_factory=lambda: int(os.getenv("COOLDOWN_SECONDS", "20").strip())
    )

    # Teams Chat Auto-Plus & Web Bridge settings
    bridge_port: int = field(
        default_factory=lambda: int(os.getenv("BRIDGE_PORT", "8765").strip())
    )
    auto_plus_enabled: bool = field(
        default_factory=lambda: os.getenv("AUTO_PLUS_ENABLED", "true").strip().lower() in ["1", "true", "yes"]
    )
    auto_plus_threshold: int = field(
        default_factory=lambda: int(os.getenv("AUTO_PLUS_THRESHOLD", "3").strip())
    )
    auto_plus_window_seconds: int = field(
        default_factory=lambda: int(os.getenv("AUTO_PLUS_WINDOW_SECONDS", "25").strip())
    )

    # Teams Chat Auto-Greeting ("Здравствуйте") settings
    auto_greeting_enabled: bool = field(
        default_factory=lambda: os.getenv("AUTO_GREETING_ENABLED", "true").strip().lower() in ["1", "true", "yes"]
    )
    auto_greeting_threshold: int = field(
        default_factory=lambda: int(os.getenv("AUTO_GREETING_THRESHOLD", "3").strip())
    )

    # Audio capture parameters
    sample_rate: int = 16000
    block_size: int = 4000

    def validate(self) -> List[str]:
        """Validates configuration and returns a list of error messages."""
        errors = []
        if not self.telegram_bot_token or "ABCDefghIJKlmno" in self.telegram_bot_token:
            errors.append("TELEGRAM_BOT_TOKEN не задан или содержит пример из шаблона. Укажите реальный токен бота от @BotFather в .env")
        if self.telegram_user_id is None or self.telegram_user_id == 123456789:
            errors.append("TELEGRAM_USER_ID не задан или содержит пример (123456789). Укажите ваш реальный числовой Telegram ID в .env")
        if not self.gemini_api_key or self.gemini_api_key.startswith("AIzaSy..."):
            errors.append("GEMINI_API_KEY не задан или содержит пример. Укажите ваш API ключ от Google AI Studio в .env")
        return errors

    @property
    def student_name(self) -> str:
        """Returns the primary student name capitalized for prompt generation."""
        if self.trigger_words:
            return self.trigger_words[0].strip().capitalize()
        return "Студент"


config = Config()
