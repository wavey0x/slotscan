"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.api.routes import contracts, layout_comparisons, storage, transactions
from app.config import get_settings
from app.db import engine
from app.models.database import Base
from app.api.dependencies import get_verification_http_client, get_web3_provider

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Silence noisy loggers
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    logger.info("Starting SlotScan API...")

    # Create tables if they don't exist (dev mode)
    settings = get_settings()
    if settings.debug:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables created/verified")

    yield

    # Shutdown
    logger.info("Shutting down SlotScan API...")
    await get_web3_provider().close()
    await get_verification_http_client().aclose()
    await engine.dispose()


def create_app() -> FastAPI:
    """Create and configure FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="SlotScan API",
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
    app.include_router(layout_comparisons.router)
    app.include_router(storage.router)
    app.include_router(transactions.router)

    # Health check
    @app.get("/health")
    async def health():
        checks = {"database": False, "rpc": False}
        try:
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
            checks["database"] = True
        except Exception as exc:
            logger.warning("Database readiness check failed: %s", exc)

        try:
            provider = get_web3_provider()
            if settings.rpc_urls:
                chain_id = next(iter(settings.rpc_urls))
                await provider.get_block_number(chain_id)
                checks["rpc"] = True
        except Exception as exc:
            logger.warning("RPC readiness check failed: %s", exc)

        ready = all(checks.values())
        return JSONResponse(
            status_code=200 if ready else 503,
            content={"status": "ok" if ready else "degraded", "checks": checks},
        )

    @app.get("/")
    async def root():
        return {
            "name": "SlotScan API",
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
