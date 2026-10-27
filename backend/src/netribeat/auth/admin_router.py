"""/api/v1/admin — user management and the audit log. Admin role required on every route."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Response, status

from netribeat.auth import audit as audit_service
from netribeat.auth.deps import (
    AdminUser,
    AuthServiceDep,
    ContextDep,
    DbDep,
    OutboxDep,
    UserServiceDep,
    flush_outbox,
    get_email_sender,
    require_admin,
)
from netribeat.auth.models import Role
from netribeat.auth.schemas import (
    AdminCreateUser,
    AdminSetActive,
    AdminSetRole,
    AdminUserList,
    AdminUserOut,
    AuditEventList,
    AuditEventOut,
)
from netribeat.auth.user_repository import UserFilter, UserSort
from netribeat.auth.user_service import to_admin_user_out
from netribeat.core.api_model import error_responses
from netribeat.email.service import EmailSender

router = APIRouter(prefix="/admin", tags=["Admin"], dependencies=[Depends(require_admin)])
E = error_responses(400, 401, 403, 404)


@router.get("/users", response_model=AdminUserList, responses=E, summary="List and search users")
async def list_users(
    admin: AdminUser,
    service: UserServiceDep,
    q: Annotated[str | None, Query(max_length=100)] = None,
    role: Role | None = None,
    is_active: Annotated[bool | None, Query(alias="isActive")] = None,
    sort: UserSort = UserSort.CREATED_DESC,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AdminUserList:
    rows, total = await service.admin_list(
        admin,
        UserFilter(q=q, role=role, is_active=is_active),
        sort=sort,
        limit=limit,
        offset=offset,
    )
    return AdminUserList(
        items=[AdminUserOut.model_validate(to_admin_user_out(u)) for u in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/users",
    status_code=status.HTTP_201_CREATED,
    response_model=AdminUserOut,
    responses=error_responses(400, 401, 403, 409),
    summary="Create a user account (no password; the person sets one via forgot-password)",
)
async def create_user(
    body: AdminCreateUser,
    admin: AdminUser,
    service: UserServiceDep,
    ctx: ContextDep,
    outbox: OutboxDep,
    background: BackgroundTasks,
    sender: Annotated[EmailSender, Depends(get_email_sender)],
) -> AdminUserOut:
    user = await service.admin_create(
        admin,
        email=body.email,
        first_name=body.first_name,
        last_name=body.last_name,
        age=body.age,
        send_invite=body.send_invite,
        ctx=ctx,
    )
    flush_outbox(outbox, background, sender)
    return AdminUserOut.model_validate(to_admin_user_out(user))


@router.get("/users/{user_id}", response_model=AdminUserOut, responses=E, summary="One user")
async def get_user(user_id: uuid.UUID, admin: AdminUser, service: UserServiceDep) -> AdminUserOut:
    return AdminUserOut.model_validate(to_admin_user_out(await service.admin_get(admin, user_id)))


@router.patch(
    "/users/{user_id}/status",
    response_model=AdminUserOut,
    responses=E,
    summary="Enable or disable an account (signs the user out everywhere)",
)
async def set_status(
    user_id: uuid.UUID,
    body: AdminSetActive,
    admin: AdminUser,
    service: UserServiceDep,
    ctx: ContextDep,
) -> AdminUserOut:
    user = await service.admin_set_active(admin, user_id, is_active=body.is_active, ctx=ctx)
    return AdminUserOut.model_validate(to_admin_user_out(user))


@router.patch(
    "/users/{user_id}/role",
    response_model=AdminUserOut,
    responses=E,
    summary="Change a user's role (signs the user out everywhere)",
)
async def set_role(
    user_id: uuid.UUID,
    body: AdminSetRole,
    admin: AdminUser,
    service: UserServiceDep,
    ctx: ContextDep,
) -> AdminUserOut:
    user = await service.admin_set_role(admin, user_id, role=body.role, ctx=ctx)
    return AdminUserOut.model_validate(to_admin_user_out(user))


@router.post(
    "/users/{user_id}/sessions/revoke-all",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=E,
    summary="Sign a user out of every device",
)
async def revoke_user_sessions(
    user_id: uuid.UUID, admin: AdminUser, service: AuthServiceDep, ctx: ContextDep
) -> Response:
    await service.admin_revoke_all(actor=admin, target_id=user_id, ctx=ctx)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/audit-events", response_model=AuditEventList, responses=E, summary="Security audit log"
)
async def audit_events(
    db: DbDep,
    action: Annotated[str | None, Query(max_length=64)] = None,
    target_user_id: Annotated[uuid.UUID | None, Query(alias="targetUserId")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AuditEventList:
    rows, total = await audit_service.list_events(
        db, action=action, target_id=target_user_id, limit=limit, offset=offset
    )
    return AuditEventList(
        items=[AuditEventOut.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )
