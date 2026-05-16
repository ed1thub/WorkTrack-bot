import os

from dotenv import load_dotenv

load_dotenv()


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _require_int_env(name: str) -> int:
    raw_value = _require_env(name)
    try:
        return int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer.") from exc


def _require_float_env(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a number.") from exc


TELEGRAM_BOT_TOKEN = _require_env("TELEGRAM_BOT_TOKEN")
TELEGRAM_SECRET_TOKEN = _require_env("TELEGRAM_SECRET_TOKEN")
ADMIN_CHAT_ID = _require_int_env("ADMIN_CHAT_ID")
DATABASE_URL = _require_env("DATABASE_URL")
HOURLY_RATE: float = _require_float_env("HOURLY_RATE", default=31.23)

# Set automatically by Vercel for cron job authentication; optional for local dev.
CRON_SECRET: str = os.getenv("CRON_SECRET", "").strip()