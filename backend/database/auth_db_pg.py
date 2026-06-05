import uuid
import asyncpg

async def create_user_async(pool: asyncpg.Pool, email: str, username: str, name: str, hashed_password: str) -> str:
    user_id = uuid.uuid4()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO users (user_id, email, username, name, hashed_password) VALUES ($1, $2, $3, $4, $5)",
            user_id, email, username, name, hashed_password
        )
    return str(user_id)

async def get_user_by_email_async(pool: asyncpg.Pool, email: str) -> dict:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT user_id, email, username, name, hashed_password FROM users WHERE email = $1",
            email
        )
    if row:
        return {
            "user_id": str(row["user_id"]), 
            "email": row["email"],
            "username": row["username"], 
            "name": row["name"],
            "hashed_password": row["hashed_password"]
        }
    return None

async def get_user_by_username_async(pool: asyncpg.Pool, username: str) -> dict:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT user_id, email, username, name, hashed_password FROM users WHERE username = $1",
            username
        )
    if row:
        return {
            "user_id": str(row["user_id"]), 
            "email": row["email"],
            "username": row["username"], 
            "name": row["name"],
            "hashed_password": row["hashed_password"]
        }
    return None

async def get_user_by_id_async(pool: asyncpg.Pool, user_id: str) -> dict:
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
             "SELECT user_id, email, username, name, hashed_password FROM users WHERE user_id = $1",
             uuid.UUID(user_id)
        )
    if row:
        return {
            "user_id": str(row["user_id"]), 
            "email": row["email"],
            "username": row["username"], 
            "name": row["name"],
            "hashed_password": row["hashed_password"]
        }
    return None
