"""FastAPI dependencies: injected infrastructure, the current user and role checks."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Annotated
from urllib.parse import urlsplit

from fastapi import BackgroundTasks, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from netribeat.auth.models import Role, User
from netribeat.auth.password_policy import BreachedPasswordChecker
from netribeat.auth.security import TokenCodec
from netribeat.auth.service import AuthService, Outbox, RequestContext
from netribeat.auth.user_service import UserService
from netribeat.clock import Clock
from netribeat.config import Settings
from netribeat.core.errors import Forbidden, Unauthorized
from netribeat.core.ratelimit import RateLimiter
from netribeat.db import get_db
from netribeat.email.service import EmailSender, deliver

REFRESH_COOKIE = "nb_refresh"
REFRESH_COOKIE_PATH = "/api/v1/auth"
CSRF_HEADER = "X-Requested-With"
CSRF_HEADER_VALUE = "NetriBeat"


def get_settings_dep(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_clock(request: Request) -> Clock:
    clock: Clock = request.app.state.clock
    return clock


def get_limiter(request: Request) -> RateLimiter:
    limiter: RateLimiter = request.app.state.limiter
    return limiter


def get_email_sender(request: Request) -> EmailSender:
    sender: EmailSender = request.app.state.email_sender
    return sender


def get_breach_checker(request: Request) -> BreachedPasswordChecker:
    checker: BreachedPasswordChecker = request.app.state.breach_checker
    return checker


def get_codec(request: Request) -> TokenCodec:
    codec: TokenCodec = request.app.state.codec
    return codec


def get_outbox() -> Outbox:
    return Outbox()


def request_context(request: Request) -> RequestContext:
    ip = request.client.host if request.client else None
    return RequestContext(ip=ip, user_agent=request.headers.get("user-agent"))


DbDep = Annotated[AsyncSession, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
ClockDep = Annotated[Clock, Depends(get_clock)]
OutboxDep = Annotated[Outbox, Depends(get_outbox)]
ContextDep = Annotated[RequestContext, Depends(request_context)]


def get_auth_service(
    db: DbDep,
    settings: SettingsDep,
    clock: ClockDep,
    limiter: Annotated[RateLimiter, Depends(get_limiter)],
    codec: Annotated[TokenCodec, Depends(get_codec)],
    breach: Annotated[BreachedPasswordChecker, Depends(get_breach_checker)],
    outbox: OutboxDep,
) -> AuthService:
    return AuthService(
        db=db,
        settings=settings,
        clock=clock,
        limiter=limiter,
        codec=codec,
        breach_checker=breach,
        outbox=outbox,
    )


AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]


def flush_outbox(outbox: Outbox, background: BackgroundTasks, sender: EmailSender) -> None:
    """Deliver queued mail after the response is sent (timing reveals nothing)."""
    for message in outbox.messages:
        background.add_task(deliver, sender, message)
    outbox.messages.clear()


@dataclass(frozen=True)
class Principal:
    user: User
    session_id: uuid.UUID


async def current_principal(request: Request, service: AuthServiceDep) -> Principal:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise Unauthorized()
    user, session_id = await service.authenticate_access_token(token.strip())
    return Principal(user=user, session_id=session_id)


PrincipalDep = Annotated[Principal, Depends(current_principal)]


async def current_user(principal: PrincipalDep) -> User:
    return principal.user


CurrentUser = Annotated[User, Depends(current_user)]


async def require_admin(user: CurrentUser) -> User:
    if user.role is not Role.ADMIN:
        raise Forbidden()
    return user


AdminUser = Annotated[User, Depends(require_admin)]


def _allowed_origins(settings: Settings) -> set[str]:
    origins = {o.rstrip("/") for o in settings.cors_origins}
    parts = urlsplit(settings.frontend_base_url)
    origins.add(f"{parts.scheme}://{parts.netloc}")
    return origins


async def csrf_protect(request: Request, settings: SettingsDep) -> None:
    """For endpoints that act on the refresh cookie. SameSite=Strict already blocks
    cross-site sends; additionally require a custom header (forces a CORS preflight)
    and, when the browser sends one, an allow-listed Origin."""
    if request.headers.get(CSRF_HEADER) != CSRF_HEADER_VALUE:
        raise Forbidden("Missing request header", code="csrf_failed")
    origin = request.headers.get("origin")
    if origin is not None and origin.rstrip("/") not in _allowed_origins(settings):
        raise Forbidden("Origin not allowed", code="csrf_failed")


def get_user_service(
    db: DbDep, clock: ClockDep, settings: SettingsDep, outbox: OutboxDep
) -> UserService:
    return UserService(db=db, clock=clock, settings=settings, outbox=outbox)


UserServiceDep = Annotated[UserService, Depends(get_user_service)]
