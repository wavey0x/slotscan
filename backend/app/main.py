"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import contracts, storage, transactions
from app.config import get_settings
from app.db import engine
from app.models.database import Base

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    logger.info("Starting StorageScan API...")

    # Create tables if they don't exist (dev mode)
    settings = get_settings()
    if settings.debug:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables created/verified")

    yield

    # Shutdown
    logger.info("Shutting down StorageScan API...")
    await engine.dispose()


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="StorageScan API",
        description="Ethereum storage analyzer API",
        version="1.0.0",
        docs_url="/api/slotscan/docs",
        redoc_url="/api/slotscan/redoc",
        lifespan=lifespan,
    )

    # CORS
    cors_origins = settings.cors_origins_list
    if settings.debug:
        # In debug mode, allow all origins to avoid local dev CORS headaches
        cors_origins = ["*"]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Routes
    app.include_router(contracts.router)
    app.include_router(storage.router)
    app.include_router(transactions.router)

    # Health check
    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/")
    async def root():
        return {
            "name": "StorageScan API",
            "version": "1.0.0",
            "docs": "/api/slotscan/docs",
        }

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.debug,
    )
