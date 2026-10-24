import hashlib
import hmac
import secrets
import time
from typing import Optional

from app.core.config import settings


def hash_password(password: str) -> str:
    """Simple secure salt+hash for passwords in MVP."""
    salt = secrets.token_hex(16)
    hashed = hashlib.sha256((salt + password).encode()).hexdigest()
    return f"{salt}${hashed}"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify password against stored salt$hash."""
    try:
        salt, expected_hash = hashed_password.split("$", 1)
        actual_hash = hashlib.sha256((salt + plain_password).encode()).hexdigest()
        return secrets.compare_digest(actual_hash, expected_hash)
    except Exception:
        return False


def _sign(payload: str) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()


def generate_token(user_id: str) -> str:
    """Bearer token ``sp_{user_id}_{issued_at}_{nonce}.{hmac}``, signed with SECRET_KEY."""
    payload = f"sp_{user_id}_{int(time.time())}_{secrets.token_hex(16)}"
    return f"{payload}.{_sign(payload)}"


def verify_token(token: Optional[str]) -> Optional[str]:
    """Return the user_id of a valid, unexpired token, else None."""
    if not token:
        return None
    if token.startswith("Bearer "):
        token = token[7:]
    payload, _, sig = token.partition(".")
    if not sig or not hmac.compare_digest(_sign(payload), sig):
        return None
    parts = payload.split("_")
    if len(parts) != 4 or parts[0] != "sp":
        return None
    try:
        issued_at = int(parts[2])
    except ValueError:
        return None
    if time.time() - issued_at > settings.AUTH_TOKEN_TTL_HOURS * 3600:
        return None
    return parts[1]
