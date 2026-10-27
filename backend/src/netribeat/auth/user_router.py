"""/api/v1/users/me — the signed-in user's own profile and password."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Response, status

from netribeat.auth.deps import (
    AuthServiceDep,
    ContextDep,
    OutboxDep,
    PrincipalDep,
    UserServiceDep,
    flush_outbox,
    get_email_sender,
)
from netribeat.auth.models import AuthSession
from netribeat.auth.schemas import (
    ChangePasswordRequest,
    ProfileUpdate,
    SessionList,
    SessionOut,
    UserOut,
)
from netribeat.auth.user_service import to_user_out
from netribeat.core.api_model import error_responses
from netribeat.core.errors import ValidationFailed
from netribeat.email.service import EmailSender

router = APIRouter(prefix="/users/me", tags=["Users"])
E = error_responses(400, 401)


@router.get("", response_model=UserOut, responses=E, summary="My profile")
async def get_me(principal: PrincipalDep) -> UserOut:
    return UserOut.model_validate(to_user_out(principal.user))


@router.patch("", response_model=UserOut, responses=E, summary="Update my name or age")
async def update_me(
    body: ProfileUpdate, principal: PrincipalDep, service: UserServiceDep
) -> UserOut:
    user = await service.update_profile(
        principal.user,
        first_name=body.first_name,
        last_name=body.last_name,
        age=body.age,
        fields_set=set(body.model_fields_set),
        extra={
            "gender": body.gender,
            "height_cm": body.height_cm,
            "weight_kg": body.weight_kg,
            "hr_rest": body.hr_rest,
        },
    )
    return UserOut.model_validate(to_user_out(user))


@router.post(
    "/password",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=E,
    summary="Change my password (needs the current one; signs out my other devices)",
)
async def change_password(
    body: ChangePasswordRequest,
    principal: PrincipalDep,
    service: AuthServiceDep,
    ctx: ContextDep,
    outbox: OutboxDep,
    background: BackgroundTasks,
    sender: Annotated[EmailSender, Depends(get_email_sender)],
) -> Response:
    if body.new_password != body.confirm_password:
        raise ValidationFailed(fields={"confirmPassword": "Passwords don't match"})
    await service.change_password(
        user=principal.user,
        session_id=principal.session_id,
        current_password=body.current_password,
        new_password=body.new_password,
        ctx=ctx,
    )
    flush_outbox(outbox, background, sender)
    return Response(status_code=status.HTTP_204_NO_CONTENT, background=background)


def _session_list(sessions: list[AuthSession], current: uuid.UUID) -> SessionList:
    return SessionList(
        items=[
            SessionOut(
                id=s.id,
                created_at=s.created_at,
                last_used_at=s.last_used_at,
                expires_at=s.expires_at,
                remember=s.remember,
                user_agent=s.user_agent,
                ip_address=s.ip_address,
                current=s.id == current,
            )
            for s in sessions
        ]
    )


@router.get("/sessions", response_model=SessionList, responses=E, summary="My signed-in devices")
async def my_sessions(principal: PrincipalDep, service: AuthServiceDep) -> SessionList:
    sessions = await service.list_sessions(principal.user.id)
    return _session_list(sessions, principal.session_id)


@router.delete(
    "/sessions/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=error_responses(401, 404),
    summary="Sign out one of my devices",
)
async def revoke_my_session(
    session_id: uuid.UUID, principal: PrincipalDep, service: AuthServiceDep, ctx: ContextDep
) -> Response:
    await service.revoke_session(owner=principal.user, session_id=session_id, ctx=ctx)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/sessions/revoke-others",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=error_responses(401),
    summary="Sign out every device except this one",
)
async def revoke_other_sessions(
    principal: PrincipalDep, service: AuthServiceDep, ctx: ContextDep
) -> Response:
    await service.revoke_other_sessions(
        owner=principal.user, current_session=principal.session_id, ctx=ctx
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
