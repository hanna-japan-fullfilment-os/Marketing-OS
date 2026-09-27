from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import (
    analytics, assets, benchmarks, brands, campaigns, defense, jobs, opportunities, products, publishing,
    repositories, research, settings_api, strategy,
)
from . import db as db_module
from .config import get_settings
from .services.creative.renderer import close_shared_renderer
from .services.seed import seed_all


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Look up init_db/SessionLocal via the module object (not copied names) so tests
    # that monkeypatch app.db.engine/SessionLocal for an isolated test database are
    # respected here too — a `from .db import SessionLocal` binding would freeze to
    # whichever engine existed the first time app.main was imported.
    db_module.init_db()
    session = db_module.SessionLocal()
    try:
        seed_all(session)
    finally:
        session.close()
    yield
    # The creative pipeline's Playwright renderer holds a headless Chromium process
    # open for reuse across renders (see services/creative/renderer.py) — close it
    # explicitly so shutdown doesn't leave a zombie browser process behind.
    await close_shared_renderer()


app = FastAPI(title="Marketing Operating System", version="0.1.0", lifespan=lifespan)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    return {"status": "ok"}


app.include_router(brands.router)
app.include_router(assets.router)
app.include_router(repositories.router)
app.include_router(settings_api.router)
app.include_router(campaigns.router)
app.include_router(research.router)
app.include_router(opportunities.router)
app.include_router(publishing.router)
app.include_router(jobs.router)
app.include_router(analytics.router)
app.include_router(strategy.router)
app.include_router(defense.router)
app.include_router(products.router)
app.include_router(benchmarks.router)
