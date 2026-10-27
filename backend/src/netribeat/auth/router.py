"""/api/v1/auth endpoints. Parse input → call one service method → return a schema."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Cookie, Depends, Request, Response, status

from netribeat.auth.deps import (
    REFRESH_COOKIE,
    REFRESH_COOKIE_PATH,
    AuthServiceDep,
    ContextDep,
    OutboxDep,
    PrincipalDep,
    SettingsDep,
    csrf_protect,
    flush_outbox,
    get_email_sender,
)
from netribeat.auth.schemas import (
    AcceptedResponse,
    EmailOnlyRequest,
    LoginMode,
    LoginRequest,
    LoginResponse,
    RegisterRequest,
    ResetPasswordRequest,
    ResetTokenResponse,
    UserOut,
    VerifyEmailRequest,
    VerifyResetOtpRequest,
)
from netribeat.auth.service import IssuedSession
from netribeat.auth.user_service import to_user_out
from netribeat.config import Settings
from netribeat.core.api_model import error_responses
from netribeat.core.errors import Unauthorized
from netribeat.email.service import EmailSender

router = APIRouter(prefix="/auth", tags=["Auth"])

SenderDep = Annotated[EmailSender, Depends(get_email_sender)]


def _set_refresh_cookie(response: Response, issued: IssuedSession, settings: Settings) -> None:
    if issued.refresh_token is None:
        return
    response.set_cookie(
        REFRESH_COOKIE,
        issued.refresh_token,
        # "Keep me signed in" → persistent cookie ending with the session; otherwise a
        # browser-session cookie (the server-side session still expires after 12 h).
        expires=issued.session_expires_at if issued.remember else None,
        path=REFRESH_COOKIE_PATH,
        domain=settings.cookie_domain,
        secure=settings.cookie_secure,
        httponly=True,
        samesite="strict",
    )


def _clear_refresh_cookie(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        REFRESH_COOKIE,
        path=REFRESH_COOKIE_PATH,
        domain=settings.cookie_domain,
        secure=settings.cookie_secure,
        httponly=True,
        samesite="strict",
    )


def _login_response(issued: IssuedSession) -> LoginResponse:
    return LoginResponse(
        token=issued.access_token,
        expires_at=issued.access_expires_at,
        user=UserOut.model_validate(to_user_out(issued.user)),
    )


@router.post(
    "/register",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AcceptedResponse,
    responses=error_responses(400, 429),
    summary="Start registration; emails a one-time verification code",
    description=(
        "Always answers 202 with the same message whether or not the email already has an "
        "account (an existing account owner is emailed instead). Public registration "
        "always creates role `user`; sending `role: admin` is rejected with 400."
    ),
)
async def register(
    body: RegisterRequest,
    service: AuthServiceDep,
    ctx: ContextDep,
    outbox: OutboxDep,
    background: BackgroundTasks,
    sender: SenderDep,
) -> AcceptedResponse:
    message = await service.register(
        first_name=body.first_name,
        last_name=body.last_name,
        email=body.email,
        password=body.password,
        ctx=ctx,
    )
    flush_outbox(outbox, background, sender)
    return AcceptedResponse(status="verification_pending", message=message)


@router.post(
    "/verify-email",
    response_model=UserOut,
    responses=error_responses(400, 409, 429),
    summary="Verify the emailed code and activate the account",
)
async def verify_email(
    body: VerifyEmailRequest,
    service: AuthServiceDep,
    ctx: ContextDep,
    outbox: OutboxDep,
    background: BackgroundTasks,
    sender: SenderDep,
) -> UserOut:
    user = await service.verify_email(email=body.email, code=body.code, ctx=ctx)
    flush_outbox(outbox, background, sender)
    return UserOut.model_validate(to_user_out(user))


@router.post(
    "/resend-verification",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AcceptedResponse,
    responses=error_responses(400, 429),
    summary="Send a new verification code (cooldown and hourly cap apply silently)",
)
async def resend_verification(
    body: EmailOnlyRequest,
    service: AuthServiceDep,
    ctx: ContextDep,
    outbox: OutboxDep,
    background: BackgroundTasks,
    sender: SenderDep,
) -> AcceptedResponse:
    message = await service.resend_verification(email=body.email, ctx=ctx)
    flush_outbox(outbox, background, sender)
    return AcceptedResponse(status="accepted", message=message)


@router.post(
    "/login",
    response_model=LoginResponse,
    responses=error_responses(400, 401, 429),
    summary="Sign in (user or admin mode); sets the HttpOnly refresh cookie",
    description=(
        "Unknown email, wrong password, unverified, disabled, password-less accounts and "
        "non-admins in admin mode all get the identical 401 `invalid_credentials`."
    ),
)
async def login(
    body: LoginRequest,
    response: Response,
    service: AuthServiceDep,
    settings: SettingsDep,
    ctx: ContextDep,
) -> LoginResponse:
    issued = await service.login(
        email=body.email,
        password=body.password,
        remember=body.remember,
        admin_mode=body.mode is LoginMode.ADMIN,
        ctx=ctx,
    )
    _set_refresh_cookie(response, issued, settings)
    response.headers["Cache-Control"] = "no-store"
    return _login_response(issued)


@router.post(
    "/refresh",
    response_model=LoginResponse,
    responses=error_responses(401, 403),
    dependencies=[Depends(csrf_protect)],
    summary="Exchange the refresh cookie for a new access token (rotates the cookie)",
)
async def refresh(
    response: Response,
    service: AuthServiceDep,
    settings: SettingsDep,
    ctx: ContextDep,
    nb_refresh: Annotated[str | None, Cookie()] = None,
) -> LoginResponse:
    if not nb_refresh:
        raise Unauthorized()
    try:
        issued = await service.refresh(refresh_token=nb_refresh, ctx=ctx)
    except Unauthorized:
        _clear_refresh_cookie(response, settings)
        raise
    _set_refresh_cookie(response, issued, settings)
    response.headers["Cache-Control"] = "no-store"
    return _login_response(issued)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=error_responses(403),
    dependencies=[Depends(csrf_protect)],
    summary="Sign out this device (revokes its session and clears the cookie)",
)
async def logout(
    request: Request,
    service: AuthServiceDep,
    settings: SettingsDep,
    ctx: ContextDep,
    nb_refresh: Annotated[str | None, Cookie()] = None,
) -> Response:
    session_id = None
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        try:
            _, session_id = await service.authenticate_access_token(header[7:].strip())
        except Unauthorized:  # an expired access token must not stop sign-out
            session_id = None
    await service.logout(session_id=session_id, refresh_token=nb_refresh, ctx=ctx)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_refresh_cookie(response, settings)
    return response


@router.get(
    "/me", response_model=UserOut, responses=error_responses(401), summary="The signed-in user"
)
async def me(principal: PrincipalDep) -> UserOut:
    return UserOut.model_validate(to_user_out(principal.user))


@router.post(
    "/forgot-password",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AcceptedResponse,
    responses=error_responses(400, 429),
    summary="Email a password-reset code (same answer whether or not the account exists)",
)
async def forgot_password(
    body: EmailOnlyRequest,
    service: AuthServiceDep,
    ctx: ContextDep,
    outbox: OutboxDep,
    background: BackgroundTasks,
    sender: SenderDep,
) -> AcceptedResponse:
    message = await service.forgot_password(email=body.email, ctx=ctx)
    flush_outbox(outbox, background, sender)
    return AcceptedResponse(status="accepted", message=message)


@router.post(
    "/verify-reset-otp",
    response_model=ResetTokenResponse,
    responses=error_responses(400, 429),
    summary="Check the emailed reset code; returns a short-lived single-use reset token",
)
async def verify_reset_otp(
    body: VerifyResetOtpRequest, service: AuthServiceDep, ctx: ContextDep, response: Response
) -> ResetTokenResponse:
    auth = await service.verify_reset_otp(email=body.email, code=body.code, ctx=ctx)
    response.headers["Cache-Control"] = "no-store"
    return ResetTokenResponse(reset_token=auth.reset_token, expires_at=auth.expires_at)


@router.post(
    "/reset-password",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=error_responses(400),
    summary="Set a new password with the reset token; signs out every device",
)
async def reset_password(
    body: ResetPasswordRequest,
    service: AuthServiceDep,
    ctx: ContextDep,
    outbox: OutboxDep,
    background: BackgroundTasks,
    sender: SenderDep,
) -> Response:
    await service.reset_password(reset_token=body.reset_token, password=body.password, ctx=ctx)
    flush_outbox(outbox, background, sender)
    return Response(status_code=status.HTTP_204_NO_CONTENT, background=background)
