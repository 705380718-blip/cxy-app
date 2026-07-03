from fastapi import APIRouter

from app.db import DB_PATH, init_db


router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str | bool]:
    init_db()
    return {
        "status": "ok",
        "service": "ai-project-manager-mvp",
        "database": str(DB_PATH),
        "database_ready": DB_PATH.exists(),
    }
