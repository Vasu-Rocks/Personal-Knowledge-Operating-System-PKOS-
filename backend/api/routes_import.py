"""Import from another PKOS database (desktop app only). Copies every user of the source database that is not here yet."""
import logging

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.dependencies import get_current_user, get_db
from core import config
from database.import_pkos import ImportSourceError, import_pkos

logger = logging.getLogger(__name__)
router = APIRouter()

# Only databases on this computer: on a server this endpoint would otherwise let users probe other hosts.
LOOPBACK = {"localhost", "127.0.0.1", "::1"}


class ImportIn(BaseModel):
    host: str = Field("localhost", max_length=100)
    port: int = Field(5433, ge=1, le=65535)
    user: str = Field("postgres", min_length=1, max_length=100)
    password: str = Field("", max_length=200)
    database: str = Field("pkos_v2", min_length=1, max_length=100)
    dry_run: bool = False


@router.post("/import/pkos")
async def import_from_pkos(payload: ImportIn, current_user: dict = Depends(get_current_user),
                           pool: asyncpg.Pool = Depends(get_db)):
    if config.ENV != "desktop":
        raise HTTPException(status_code=404, detail="Not found")
    if payload.host.strip().lower() not in LOOPBACK:
        raise HTTPException(status_code=400, detail="Only databases on this computer (localhost) can be imported.")
    try:
        result = await import_pkos(pool, host=payload.host.strip(), port=payload.port, user=payload.user,
                                   password=payload.password, database=payload.database, dry_run=payload.dry_run)
    except ImportSourceError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        logger.exception("Import failed")
        raise HTTPException(status_code=500, detail="The import failed and nothing was changed. See the logs for details.")
    logger.info(f"Import by user {current_user.get('user_id')}: {result}")
    return result
