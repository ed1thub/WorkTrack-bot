import json
import os

from dotenv import load_dotenv

load_dotenv()


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _require_json_env(name: str) -> dict:
    raw_value = _require_env(name)
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{name} must contain valid JSON.") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError(f"{name} must decode to a JSON object.")
    return parsed


def _require_int_env(name: str) -> int:
    raw_value = _require_env(name)
    try:
        return int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer.") from exc


TELEGRAM_BOT_TOKEN = _require_env("TELEGRAM_BOT_TOKEN")
TELEGRAM_SECRET_TOKEN = _require_env("TELEGRAM_SECRET_TOKEN")
ADMIN_CHAT_ID = _require_int_env("ADMIN_CHAT_ID")
GOOGLE_CREDENTIALS_JSON = _require_json_env("GOOGLE_CREDENTIALS_JSON")
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID", "").strip() or os.getenv("GOOGLE_SHEET_ID", "").strip()

if not SPREADSHEET_ID:
    raise RuntimeError("Missing required environment variable: SPREADSHEET_ID (or GOOGLE_SHEET_ID)")