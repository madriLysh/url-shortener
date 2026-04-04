from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from scalar_fastapi import get_scalar_api_reference

from api.admin import router as admin_router
from api.health import router as health_router
from api.routes import router as url_router
from config import Config
from log import get_logger

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Application starting up...")

    from sqlalchemy import text

    from infrastructure.database import SessionLocal, engine
    from infrastructure.redis_client import RedisClient

    db = SessionLocal()
    redis = None
    scheduler_started = False

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("Database connection verified")
    except Exception as e:
        logger.error(f"Database unavailable: {e}")
        raise RuntimeError("Cannot start without database") from e

    try:
        redis = RedisClient.from_pool()
        redis.client.ping()
        logger.info("Redis connection verified")
    except Exception as e:
        logger.warning(f"Redis unavailable: {e}")

    try:
        from scheduler import start_scheduler, stop_scheduler
        from services import URLService

        service = URLService(redis_client=redis, db_session=db) # type: ignore
        app.state.stop_scheduler = stop_scheduler
        app.state.db = db

        start_scheduler(service)
        scheduler_started = True
        logger.info("Background scheduler started")

    except ImportError:
        logger.warning("Scheduler module not found")
    except Exception as e:
        logger.error(f"Failed to start scheduler: {e}")

    yield

    logger.info("Application shutting down...")

    if scheduler_started and hasattr(app.state, 'stop_scheduler'):
        try:
            app.state.stop_scheduler()
            logger.info("Scheduler stopped gracefully")
        except Exception as e:
            logger.error(f"Error stopping scheduler: {e}")

    try:
        db.close()
        logger.info("Database session closed")
    except Exception as e:
        logger.error(f"Error closing database session: {e}")

    try:
        engine.dispose()
        logger.info("Database connections disposed")
    except Exception as e:
        logger.error(f"Error disposing database engine: {e}")

    logger.info("Shutdown complete")


def create_app() -> FastAPI:
    app = FastAPI(
        title="URL Shortener API",
        version="1.0.0",
        description="High-performance URL shortener with analytics, "
        "rate limiting, and admin controls.",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url="/openapi.json",
    )
    return app


def setup_middleware(app: FastAPI) -> None:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=Config.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def add_request_id(request: Request, call_next):
        import uuid
        request_id = str(uuid.uuid4())[:8]
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        if request.url.path in ["/health", "/docs", "/redoc", "/openapi.json", "/scalar"]:
            return await call_next(request)

        import time
        start = time.time()
        response = await call_next(request)
        duration = time.time() - start

        logger.info(
            f"{request.method} {request.url.path} → "
            f"{response.status_code} ({duration:.3f}s)"
        )
        return response


def setup_routers(app: FastAPI) -> None:
    app.include_router(health_router, tags=["Health"])
    app.include_router(url_router, tags=["URLs"])
    app.include_router(admin_router, tags=["Admin"])


def setup_scalar_docs(app: FastAPI) -> None:
    @app.get("/scalar", include_in_schema=False)
    async def scalar_html():
        return get_scalar_api_reference(
            openapi_url="/openapi.json",
            title="URL Shortener API",
            hide_download_button=False,
            dark_mode=True,
        )


def setup_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError):
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc)}
        )

    @app.exception_handler(Exception)
    async def catch_all_handler(request: Request, exc: Exception):
        logger.exception("Unhandled exception")
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"}
        )


def build_application() -> FastAPI:
    app = create_app()
    setup_middleware(app)
    setup_scalar_docs(app)
    setup_routers(app)
    setup_exception_handlers(app)
    return app


app = build_application()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True, log_level="info")
