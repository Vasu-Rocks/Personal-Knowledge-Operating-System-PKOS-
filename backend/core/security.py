import jwt
import bcrypt
from datetime import datetime, timedelta, timezone
from typing import Optional

# Secret key generation normally injected via OS Env
SECRET_KEY = "pkos_v2_super_secret_temporary_key_replace_in_prod"
ALGORITHM = "HS256"
# Explicit 30 day lifetime to reduce friction per user requirement
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 30 

def verify_password(plain_password: str, hashed_password: str) -> bool:
    # 72-byte limit protection. Python strings are utf-8.
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
