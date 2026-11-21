from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel
import asyncpg
from database.auth_db_pg import (
    get_user_by_username_async,
    get_user_by_email_async,
    create_user_async
)
from core.security import verify_password, get_password_hash, create_access_token
from api.dependencies import get_db, get_current_user

router = APIRouter()

class SetupRequest(BaseModel):
    email: str
    username: str
    name: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str

@router.post("/register", response_model=Token)
async def register(user_data: SetupRequest, pool: asyncpg.Pool = Depends(get_db)):
    # 1. Validate email syntax
    if "@" not in user_data.email or "." not in user_data.email.split("@")[-1]:
        raise HTTPException(status_code=400, detail="Invalid email address syntax (e.g., user@gmail.com)")

    # 2. Prevent spaces or special characters in the username if preferred (optional, simple validation)
    username_clean = user_data.username.strip()
    if not username_clean:
        raise HTTPException(status_code=400, detail="Username cannot be empty")
        
    # 3. Check if email already registered
    if await get_user_by_email_async(pool, user_data.email):
        raise HTTPException(status_code=400, detail="Email is already registered")

    # 4. Check if username already registered
    if await get_user_by_username_async(pool, username_clean):
        raise HTTPException(status_code=400, detail="Username is already taken")
        
    try:
        hashed_password = get_password_hash(user_data.password)
    except ValueError:
        raise HTTPException(status_code=400, detail="Password is too long (max 71 characters).")
        
    try:
        user_id = await create_user_async(
            pool=pool,
            email=user_data.email,
            username=username_clean,
            name=user_data.name.strip(),
            hashed_password=hashed_password
        )
    except asyncpg.UniqueViolationError:
        # Race condition guard: another request claimed the email/username
        # fractions of a second before this one completed
        raise HTTPException(status_code=409, detail="Email or username was just taken. Please try again.")
    
    # Automatically log them in by returning the token
    access_token = create_access_token(data={"sub": user_id})
    return {"access_token": access_token, "token_type": "bearer"}

@router.post("/login", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends(), pool: asyncpg.Pool = Depends(get_db)):
    # 1. Blind query fallback: check email first, then username
    user = await get_user_by_email_async(pool, form_data.username)
    if not user:
        user = await get_user_by_username_async(pool, form_data.username)

    # 2. Check credentials
    if not user or not verify_password(form_data.password, user["hashed_password"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect credentials. Please verify your email/username and password.",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
    access_token = create_access_token(data={"sub": user["user_id"]})
    return {"access_token": access_token, "token_type": "bearer"}

@router.get("/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    """
    Returns the profile data of the logged-in user to hydrate the frontend state.
    """
    return {
        "user_id": current_user["user_id"],
        "email": current_user["email"],
        "username": current_user["username"],
        "name": current_user["name"]
    }
