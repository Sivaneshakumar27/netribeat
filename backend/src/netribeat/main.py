"""App factory: routers, exception handlers, middleware and injected infrastructure."""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic.alias_generators import to_camel
from redis.asyncio import Redis
from redis.exceptions import RedisError
from starlette.exceptions import HTTPException as StarletteHTTPException

from netribeat.auth.admin_router import router as admin_router
from netribeat.auth.password_policy import BreachedPasswordChecker, HibpRangeChecker, NoBreachCheck
from netribeat.auth.router import router as auth_router
from netribeat.auth.security import TokenCodec
from netribeat.auth.user_router import router as users_router
from netribeat.clock import Clock, SystemClock
from netribeat.config import Settings, get_settings
from netribeat.core.errors import AppError
from netribeat.core.logging_config import configure_logging
from netribeat.core.middleware import (
    AccessLogMiddleware,
    BodyLimitMiddleware,
    SecurityHeadersMiddleware,
)
from netribeat.core.ratelimit import RateLimiter, RedisRateLimiter
from netribeat.db import init_db, make_engine, make_sessionmaker
from netribeat.email.service import EmailSender, build_email_sender
from netribeat.email.validation import INVALID_EMAIL_MESSAGE
from netribeat.health.router import router as health_router

log = logging.getLogger(__name__)

API_PREFIX = "/api/v1"

# UI copy for missing / invalid fields (design-spec §3.1).
_MISSING_MESSAGES = {
    "email": INVALID_EMAIL_MESSAGE,
    "password": "Enter your password",
    "confirmPassword": "Confirm your password",
    "firstName": "Enter your first name",
    "lastName": "Enter your last name",
    "code": "Enter the code from the email",
}
_MODEL_FIELD_MSG = re.compile(r"^(?:Value error, )?([a-z_]+): (.+)$")


def _validation_fields(exc: RequestValidationError) -> dict[str, str]:
    fields: dict[str, str] = {}
    for err in exc.errors():
        loc = [str(p) for p in err.get("loc", ()) if p not in ("body", "query", "path", "header")]
        msg = str(err.get("msg", "Invalid value"))
        if not loc:
            m = _MODEL_FIELD_MSG.match(msg)
            if m:
                fields.setdefault(to_camel(m.group(1)), m.group(2))
            else:
                fields.setdefault("body", msg.removeprefix("Value error, "))
            continue
        name = loc[0] if len(loc) == 1 else ".".join(loc)
        if err.get("type") == "missing":
            msg = _MISSING_MESSAGES.get(name, "This field is required")
        elif name == "code" and err.get("type") == "string_pattern_mismatch":
            msg = "Enter the numeric code from the email"
        elif name == "role" and err.get("type") == "literal_error":
            msg = "Public registration can only create a user account"
        else:
            msg = msg.removeprefix("Value error, ")
        fields.setdefault(name, msg)
    return fields


def _error(
    status: int,
    code: str,
    message: str,
    fields: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {"code": code, "message": message}
    if fields:
        body["fields"] = fields
    return JSONResponse(body, status_code=status, headers=headers)


def install_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(_: Request, exc: AppError) -> JSONResponse:
        return _error(exc.status_code, exc.code, exc.message, exc.fields, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _error(400, "validation_error", "Some fields are invalid", _validation_fields(exc))

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        codes = {404: "not_found", 405: "method_not_allowed"}
        message = "Not found" if exc.status_code == 404 else str(exc.detail)
        return _error(
            exc.status_code,
            codes.get(exc.status_code, "http_error"),
            message,
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RedisError)
    async def _redis_down(request: Request, exc: RedisError) -> JSONResponse:
        # Rate limiting fails closed: without Redis we refuse instead of skipping limits.
        log.error("redis_unavailable", extra={"path": request.url.path})
        return _error(
            503,
            "service_unavailable",
            "The service is temporarily unavailable. Please try again shortly",
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled_error", extra={"path": request.url.path})
        return _error(500, "internal_error", "Something went wrong")


def create_app(
    settings: Settings | None = None,
    *,
    clock: Clock | None = None,
    limiter: RateLimiter | None = None,
    email_sender: EmailSender | None = None,
    breach_checker: BreachedPasswordChecker | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = make_engine(settings.database_url)
        await init_db(engine)
        app.state.engine = engine
        app.state.sessionmaker = make_sessionmaker(engine)
        redis: Redis | None = None
        if limiter is None:
            redis = Redis.from_url(settings.redis_url, decode_responses=True)
            app.state.limiter = RedisRateLimiter(redis)
        app.state.redis = redis
        try:
            yield
        finally:
            if redis is not None:
                await redis.aclose()
            await engine.dispose()

    app = FastAPI(
        title="NetriBeat API",
        version="0.2.0",
        description=(
            "Backend for NetriBeat: registration with email verification, login "
            "(user and admin), password reset, profile and admin user management."
        ),
        lifespan=lifespan,
        docs_url="/api/docs" if settings.docs_enabled else None,
        redoc_url="/api/redoc" if settings.docs_enabled else None,
        openapi_url="/api/openapi.json" if settings.docs_enabled else None,
    )
    app.state.settings = settings
    app.state.clock = clock or SystemClock()
    if limiter is not None:
        app.state.limiter = limiter
    app.state.email_sender = email_sender or build_email_sender(settings)
    app.state.breach_checker = breach_checker or (
        HibpRangeChecker() if settings.hibp_check_enabled else NoBreachCheck()
    )
    app.state.codec = TokenCodec(settings.jwt_secret.get_secret_value(), settings.jwt_algorithm)

    install_exception_handlers(app)

    # Order: the last added runs first (outermost).
    app.add_middleware(BodyLimitMiddleware, max_bytes=settings.max_json_body_bytes)
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.is_production)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=["Authorization", "Content-Type", "X-Requested-With"],
            max_age=600,
        )
    app.add_middleware(AccessLogMiddleware)

    for router in (health_router, auth_router, users_router, admin_router):
        app.include_router(router, prefix=API_PREFIX)
    return app


def app_factory() -> FastAPI:
    """Entry point for `uvicorn --factory netribeat.main:app_factory`."""
    return create_app()
