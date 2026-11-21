from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
import jwt
import asyncpg
from core.security import SECRET_KEY, ALGORITHM
from database.auth_db_pg import get_user_by_id_async

# This URL tells the Swagger UI where to send the credentials to get the token.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/login")

def get_db(request: Request) -> asyncpg.Pool:
    """Dependency injecting the globally managed asyncpg connection pool into routes."""
    return request.app.state.pool

async def get_current_user(token: str = Depends(oauth2_scheme), pool: asyncpg.Pool = Depends(get_db)) -> dict:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except jwt.PyJWTError:
        raise credentials_exception
        
    try:
        user = await get_user_by_id_async(pool, user_id)
    except ValueError:
        raise credentials_exception
    if user is None:
        raise credentials_exception
    return user
