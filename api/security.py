import hmac
import config


def verify_token(header_value: str | None) -> bool:
    if not header_value or not config.TELEGRAM_SECRET_TOKEN:
        return False
    return hmac.compare_digest(header_value.strip(), config.TELEGRAM_SECRET_TOKEN)
