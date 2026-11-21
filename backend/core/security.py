import jwt
import bcrypt
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("TOKEN_TTL_MINUTES", str(60 * 24 * 30)))  # default 30 days

def _get_secret_key() -> str:
    key = os.getenv("PKOS_SECRET_KEY")
    if key:
        return key
    if os.getenv("ENV", "dev").lower() == "prod":
        raise RuntimeError("PKOS_SECRET_KEY must be set when ENV=prod.")
    # Dev fallback: random key (tokens reset on restart, but app works)
    fallback = secrets.token_hex(32)
    import logging
    logging.getLogger(__name__).warning(
        "PKOS_SECRET_KEY not set — using a random key. "
        "Tokens will be invalidated on restart. Set PKOS_SECRET_KEY in your .env for persistence."
    )
    return fallback

SECRET_KEY = _get_secret_key()

def verify_password(plain_password: str, hashed_password: str) -> bool:
    if len(plain_password.encode('utf-8')) > 71:
        return False
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))

def get_password_hash(password: str) -> str:
    if len(password.encode('utf-8')) > 71:
        raise ValueError("Password is too long.")
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt
