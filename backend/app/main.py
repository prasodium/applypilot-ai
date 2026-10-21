"""FastAPI application factory."""
from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import asynccontextmanager
from pathlib import Path

from alembic.config import Config as AlembicConfig
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError as PydanticValidationError
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException

from alembic import command
from app.config import BACKEND_DIR, Settings, get_settings
from app.core.redact import RedactingFilter
from app.db import make_engine, make_sessionmaker
from app.errors import AppError
from app.ratelimit import RateLimiter

log = logging.getLogger("applypilot")


def init_db(settings: Settings) -> None:
    """Apply Alembic migrations to the configured database (also creates the data directory for SQLite)."""
    engine = make_engine(settings.database_url)
    cfg = AlembicConfig(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.attributes["url"] = settings.database_url
    command.upgrade(cfg, "head")
    engine.dispose()


def get_db(request: Request) -> Iterator[Session]:
    """One transaction per request: commit on success, roll back on error."""
    s: Session = request.app.state.sessionmaker()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


DB = Depends(get_db)


def create_app(settings: Settings | None = None, *, migrate: bool = True) -> FastAPI:
    settings = settings or get_settings()
    logging.getLogger().setLevel(settings.log_level)
    logging.getLogger().addFilter(RedactingFilter())
    for h in logging.getLogger().handlers:
        h.addFilter(RedactingFilter())

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        from app.services.workflow import recover_interrupted

        if migrate:
            init_db(settings)
        with app.state.sessionmaker() as s:
            recover_interrupted(s)  # runs left mid-flight by a crash become resumable (or UNCONFIRMED for submits)
            s.commit()
        yield
        await app.state.runner.shutdown()
        app.state.engine.dispose()

    app = FastAPI(title="ApplyPilot AI", version="0.1.0", lifespan=lifespan,
                  docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)
    app.state.settings = settings
    app.state.engine = make_engine(settings.database_url)
    app.state.sessionmaker = make_sessionmaker(app.state.engine)
    app.state.limiter = RateLimiter()

    from app.ai.provider import build_provider
    from app.services.workflow import WorkflowRunner

    app.state.ai = build_provider(settings)
    app.state.runner = WorkflowRunner(app)

    app.add_middleware(
        CORSMiddleware, allow_origins=[settings.frontend_origin], allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"], allow_headers=["Content-Type", "Idempotency-Key"],
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        resp.headers.setdefault("Cache-Control", "no-store")
        return resp

    @app.exception_handler(AppError)
    async def app_error(_: Request, exc: AppError):
        return JSONResponse({"error": {"code": exc.code, "message": exc.message, "details": exc.details}},
                            status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        errs = [{"field": ".".join(str(x) for x in e["loc"] if x != "body"), "message": e["msg"]} for e in exc.errors()]
        return JSONResponse({"error": {"code": "validation_error", "message": "Some fields are invalid.", "details": {"errors": errs}}},
                            status_code=422)

    @app.exception_handler(PydanticValidationError)
    async def model_validation_error(_: Request, exc: PydanticValidationError):
        # Raised by services that re-validate merged data (e.g. PATCH preferences); never a 500.
        errs = [{"field": ".".join(str(x) for x in e["loc"]), "message": e["msg"]} for e in exc.errors()]
        return JSONResponse({"error": {"code": "validation_error", "message": "Some fields are invalid.", "details": {"errors": errs}}},
                            status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException):
        return JSONResponse({"error": {"code": "http_error", "message": str(exc.detail), "details": {}}}, status_code=exc.status_code)

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception):
        log.exception("unhandled error")  # stack trace goes to the (redacted) server log only
        return JSONResponse({"error": {"code": "internal_error", "message": "Something went wrong. Check the server log.", "details": {}}},
                            status_code=500)

    from app.api import answers, applications, documents, jobs, meta, profile, workflows

    for r in (meta.router, answers.router, profile.router, documents.router, jobs.router, applications.router, workflows.router):
        app.include_router(r, prefix="/api")

    if settings.mount_mock_employer and not settings.is_production:
        from app.mock_employer.app import build_mock_employer

        app.mount("/mock-employer", build_mock_employer())
    return app


def app_factory() -> FastAPI:  # for `uvicorn app.main:app_factory --factory`
    return create_app()


_ = Path
