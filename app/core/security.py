import hashlib
import secrets
import time
from typing import Optional


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


def generate_token(user_id: str) -> str:
    """Generate a token string for simple bearer authentication."""
    random_str = secrets.token_urlsafe(32)
    timestamp = int(time.time())
    return f"sp_{user_id}_{timestamp}_{random_str}"


def extract_user_id_from_token(token: str) -> Optional[str]:
    """Extract user_id from bearer token."""
    if not token:
        return None
    if token.startswith("Bearer "):
        token = token[7:]
    parts = token.split("_")
    if len(parts) >= 4 and parts[0] == "sp":
        return parts[1]
    return None
