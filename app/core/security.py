from datetime import datetime, timedelta, timezone
from typing import Optional
from jose import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError
from cryptography.fernet import Fernet
from app.config import settings

_ph = PasswordHasher()  # defaults: time_cost=3, memory_cost=65536, parallelism=4
_fernet = Fernet(settings.ENCRYPTION_KEY.encode() if isinstance(settings.ENCRYPTION_KEY, str) else settings.ENCRYPTION_KEY)


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _ph.verify(hashed, plain)
    except (VerifyMismatchError, InvalidHashError):
        return False


def _now() -> datetime:
    return datetime.now(timezone.utc)


def create_access_token(subject: str, role: str, expires_delta: Optional[timedelta] = None) -> str:
    now = _now()
    expire = now + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    payload = {"sub": subject, "role": role, "exp": expire, "iat": now}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(subject: str, role: str) -> str:
    now = _now()
    expire = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {"sub": subject, "role": role, "exp": expire, "type": "refresh"}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])


def encrypt_token(token: str) -> str:
    if not token:
        return None
    return _fernet.encrypt(token.encode()).decode()


def decrypt_token(encrypted: str) -> str:
    if not encrypted:
        return None
    return _fernet.decrypt(encrypted.encode()).decode()
