"""Passwords use scrypt; only a hash of the opaque session cookie is stored."""
import hashlib
import hmac
import secrets

from server.errors import ServiceError


def hash_password(password: str) -> str:
    if not 10 <= len(password) <= 1024:
        raise ServiceError("PASSWORD_INVALID", "密码长度须为 10 至 1024 个字符。")
    salt = secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
    return f"scrypt${salt}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, salt, expected = encoded.split("$")
        if scheme != "scrypt" or len(password) > 1024:
            return False
        actual = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1)
        return hmac.compare_digest(actual.hex(), expected)
    except (ValueError, TypeError):
        return False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_tokens() -> tuple[str, str]:
    return secrets.token_urlsafe(32), secrets.token_urlsafe(32)


def public_user(user) -> dict:
    return {"id": user["id"], "username": user["username"], "role": user["role"],
            "must_change_password": bool(user["must_change_password"])}
