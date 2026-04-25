import hashlib
import hmac
import os

from dotenv import load_dotenv

load_dotenv()

_APP_SECRET: bytes = os.environ["WHATSAPP_APP_SECRET"].encode()


def verify_signature(raw_body: bytes, signature_header: str | None) -> bool:
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    received = signature_header.removeprefix("sha256=")
    computed = hmac.new(_APP_SECRET, raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed, received)
