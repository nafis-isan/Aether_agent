from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.health import router as health_router
from app.api.routes.auth import router as auth_router
from app.api.routes.chat import router as chat_router
from app.api.routes.memory import router as memory_router
from app.api.routes.realtime import router as realtime_router
from app.api.routes.tasks import router as tasks_router
from app.api.routes.approvals import router as approvals_router
from app.config import settings

allowed_origins = [
    origin.strip() for origin in settings.cors_allowed_origins.split(",") if origin.strip()
]

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Aether personal AI assistant backend foundation.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(memory_router)
app.include_router(tasks_router)
app.include_router(approvals_router)
app.include_router(realtime_router)


@app.get("/")
async def root() -> dict:
    return {
        "message": f"{settings.app_name} backend is running",
        "environment": settings.app_env,
    }


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": settings.app_name}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=settings.app_debug)
