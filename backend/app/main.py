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
from app.api.dependencies import get_verification_http_client, get_web3_provider
from app.services.tracer.rpc_client import TraceRPCClient

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

    yield

    # Shutdown
    logger.info("Shutting down SlotScan API...")
    await get_web3_provider().close()
    await get_verification_http_client().aclose()
    await engine.dispose()


def create_api() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="SlotScan API",
        description="Ethereum storage analyzer API",
        version="1.0.0",
        docs_url="/api/slotscan/docs",
        redoc_url="/api/slotscan/redoc",
        lifespan=lifespan,
    )

    # Routes
    app.include_router(contracts.router)
    app.include_router(layout_comparisons.router)
    app.include_router(storage.router)
    app.include_router(transactions.router)

    # Health check
    @app.get("/health")
    async def health():
        checks = {"database": False, "rpc": False, "native_trace": False}
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
                await TraceRPCClient(provider, settings).check_support(chain_id)
                checks["native_trace"] = True
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


def configure_cors(app: FastAPI) -> CORSMiddleware:
    """Wrap the full application so error responses also receive CORS headers."""
    settings = get_settings()
    cors_origins = settings.cors_origins_list
    if settings.debug:
        # In debug mode, allow all origins to avoid local dev CORS headaches
        cors_origins = ["*"]
    return CORSMiddleware(
        app=app,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


def create_app() -> CORSMiddleware:
    """Create the complete ASGI application."""
    return configure_cors(create_api())


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
