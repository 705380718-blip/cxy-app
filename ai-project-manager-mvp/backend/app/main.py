from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db import init_db
from app.routers.assets import router as assets_router
from app.routers.documents import router as documents_router
from app.routers.health import router as health_router
from app.routers.inbox import router as inbox_router
from app.routers.projects import router as projects_router
from app.routers.settings import router as settings_router
from app.routers.system import router as system_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="AI Project Manager MVP API",
    version="0.1.0-p0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(projects_router)
app.include_router(assets_router)
app.include_router(inbox_router)
app.include_router(documents_router)
app.include_router(settings_router)
app.include_router(system_router)
