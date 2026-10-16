from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.config import settings
from database import engine
from migrations import migrate
from routers import router as api_router

# Import all models so every table is registered on the metadata.
import models  # noqa: F401


@asynccontextmanager
async def lifespan(_app: FastAPI):
    async with engine.begin() as conn:
        await migrate(conn)
    yield
    await engine.dispose()


app = FastAPI(title="Retail POS API", version="0.1.0", lifespan=lifespan)

# The web app is served from the API's own origin and needs no CORS. Other clients
# (e.g. a packaged mobile/desktop app) are allowed by listing their origins,
# comma-separated, in CORS_ORIGINS.
cors_origins = [o.strip() for o in settings.CORS_ORIGINS.split(",") if o.strip()]
if cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_methods=["*"],
        allow_headers=["Authorization", "Content-Type"],
    )

app.include_router(api_router, prefix="/api")

