from fastapi import APIRouter

from app.config import settings
from app.database import get_database_status

router = APIRouter(prefix="/api/v1", tags=["health"])


@router.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "service": settings.app_name,
        "environment": settings.app_env,
        "database": await get_database_status(),
        "frontend_url": settings.frontend_url,
    }


@router.get("/health/live")
async def health_live() -> dict:
    return {"status": "alive", "service": settings.app_name}
