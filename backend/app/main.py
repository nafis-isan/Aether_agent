import ipaddress
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes.health import router as health_router
from app.api.routes.auth import router as auth_router
from app.api.routes.chat import router as chat_router
from app.api.routes.memory import router as memory_router
from app.api.routes.realtime import router as realtime_router
from app.api.routes.tasks import router as tasks_router
from app.api.routes.approvals import router as approvals_router
from app.api.routes.browser import router as browser_router
from app.browser.manager import get_browser_manager
from app.config import settings

allowed_origins = [
    origin.strip() for origin in settings.cors_allowed_origins.split(",") if origin.strip()
]
allowed_origin_set = set(allowed_origins)

@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await get_browser_manager().close()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Aether personal AI assistant backend foundation.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def restrict_local_mode_to_loopback(request, call_next):
    if settings.local_auth_mode:
        client = request.client
        if client is None:
            return JSONResponse(status_code=403, content={"detail": "Local access only"})
        try:
            if not ipaddress.ip_address(client.host).is_loopback:
                return JSONResponse(status_code=403, content={"detail": "Local access only"})
        except ValueError:
            return JSONResponse(status_code=403, content={"detail": "Local access only"})

        origin = request.headers.get("origin")
        if origin is not None and origin not in allowed_origin_set:
            return JSONResponse(status_code=403, content={"detail": "Origin is not allowed in local mode"})
    return await call_next(request)


app.include_router(health_router)
app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(memory_router)
app.include_router(tasks_router)
app.include_router(approvals_router)
app.include_router(browser_router)
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

    host = "127.0.0.1" if settings.local_auth_mode else "0.0.0.0"
    uvicorn.run("app.main:app", host=host, port=8000, reload=settings.app_debug)
