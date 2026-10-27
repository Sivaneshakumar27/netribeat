"""User profile and administration rules. Every method takes the acting user and
enforces authorisation itself (routers never decide access)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from netribeat.auth import audit
from netribeat.auth import user_repository as repo
from netribeat.auth.models import Role, User, UserSource
from netribeat.auth.service import Outbox, RequestContext, revoke_user_sessions
from netribeat.auth.user_repository import UserFilter, UserSort
from netribeat.clock import Clock
from netribeat.config import Settings
from netribeat.core.errors import BadRequest, Conflict, Forbidden, NotFound
from netribeat.email.service import OutgoingEmail, render


def to_user_out(user: User) -> dict[str, object]:
    return {
        "id": user.id,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "name": user.display_name,
        "role": user.role,
        "email_verified": user.email_verified_at is not None,
        "has_password": user.has_password,
        "is_active": user.is_active,
        "age": user.age,
        "gender": user.gender.value if user.gender else None,
        "height_cm": user.height_cm,
        "weight_kg": user.weight_kg,
        "hr_rest": user.hr_rest,
        "created_at": user.created_at,
        "last_login_at": user.last_login_at,
    }


def to_admin_user_out(user: User) -> dict[str, object]:
    return {
        **to_user_out(user),
        "source": user.source,
        "token_version": user.token_version,
        "updated_at": user.updated_at,
    }


class UserService:
    def __init__(
        self, *, db: AsyncSession, clock: Clock, settings: Settings, outbox: Outbox
    ) -> None:
        self.db = db
        self.clock = clock
        self.s = settings
        self.outbox = outbox

    # ---------------------------------------------------------------- self-service

    async def update_profile(
        self,
        actor: User,
        *,
        first_name: str | None,
        last_name: str | None,
        age: int | None,
        fields_set: set[str],
        extra: dict[str, object] | None = None,
    ) -> User:
        if "first_name" in fields_set and first_name is not None:
            actor.first_name = first_name
        if "last_name" in fields_set and last_name is not None:
            actor.last_name = last_name
        if "age" in fields_set:
            actor.age = age
        for key in ("gender", "height_cm", "weight_kg", "hr_rest"):
            if key in fields_set and extra is not None:
                setattr(actor, key, extra.get(key))
        audit.record(
            self.db,
            action="user.profile_updated",
            now=self.clock.now(),
            actor_id=actor.id,
            target_id=actor.id,
            details={"fields": sorted(fields_set)},
        )
        await self.db.commit()
        await self.db.refresh(actor)
        return actor

    # ---------------------------------------------------------------- admin

    @staticmethod
    def _require_admin(actor: User) -> None:
        if actor.role is not Role.ADMIN:
            raise Forbidden()

    async def admin_list(
        self, actor: User, flt: UserFilter, *, sort: UserSort, limit: int, offset: int
    ) -> tuple[Sequence[User], int]:
        self._require_admin(actor)
        return await repo.list_users(self.db, flt, sort=sort, limit=limit, offset=offset)

    async def admin_get(self, actor: User, user_id: uuid.UUID) -> User:
        self._require_admin(actor)
        user = await repo.get_by_id(self.db, user_id)
        if user is None:
            raise NotFound("User not found")
        return user

    async def admin_create(
        self,
        actor: User,
        *,
        email: str,
        first_name: str,
        last_name: str,
        age: int | None,
        send_invite: bool,
        ctx: RequestContext,
    ) -> User:
        """Create a `user` account without a password. The person sets one through
        forgot-password, which also verifies the email. Admins are never created here:
        promote through the role endpoint, or provision with the CLI."""
        self._require_admin(actor)
        now = self.clock.now()
        user = User(
            email=email,
            first_name=first_name,
            last_name=last_name,
            age=age,
            role=Role.USER,
            password_hash=None,
            email_verified_at=None,
            is_active=True,
            source=UserSource.ADMIN,
        )
        repo.add(self.db, user)
        try:
            await self.db.flush()
        except IntegrityError:
            await self.db.rollback()
            raise Conflict("A user with this email already exists", code="email_taken") from None
        audit.record(
            self.db,
            action="admin.user_created",
            now=now,
            actor_id=actor.id,
            target_id=user.id,
            ip=ctx.ip,
        )
        await self.db.commit()
        await self.db.refresh(user)
        if send_invite:
            subject, body = render(
                "account_invited",
                name=first_name,
                email=email,
                forgot_url=self.s.frontend_base_url.rstrip("/") + "/forgot-password",
            )
            self.outbox.add(OutgoingEmail(email, subject, body, "account_invited"))
        return user

    async def _lock_target(self, actor: User, user_id: uuid.UUID) -> User:
        self._require_admin(actor)
        user = await repo.get_by_id(self.db, user_id, for_update=True)
        if user is None:
            raise NotFound("User not found")
        return user

    async def _guard_last_admin(self, target: User) -> None:
        if (
            target.role is Role.ADMIN
            and target.is_active
            and await repo.count_active_admins(self.db) <= 1
        ):
            raise BadRequest(
                "The last active admin can't be demoted or disabled", code="last_admin"
            )

    async def admin_set_active(
        self, actor: User, user_id: uuid.UUID, *, is_active: bool, ctx: RequestContext
    ) -> User:
        target = await self._lock_target(actor, user_id)
        if target.id == actor.id:
            raise BadRequest("You can't disable your own account", code="cannot_modify_self")
        if target.is_active == is_active:
            return target
        if not is_active:
            await self._guard_last_admin(target)
        now = self.clock.now()
        target.is_active = is_active
        target.token_version += 1
        await revoke_user_sessions(
            self.db, target.id, now=now, reason="disabled" if not is_active else "enabled"
        )
        audit.record(
            self.db,
            action="admin.user_enabled" if is_active else "admin.user_disabled",
            now=now,
            actor_id=actor.id,
            target_id=target.id,
            ip=ctx.ip,
        )
        await self.db.commit()
        await self.db.refresh(target)
        return target

    async def admin_set_role(
        self, actor: User, user_id: uuid.UUID, *, role: Role, ctx: RequestContext
    ) -> User:
        target = await self._lock_target(actor, user_id)
        if target.id == actor.id:
            raise BadRequest("You can't change your own role", code="cannot_modify_self")
        if target.role is role:
            return target
        if role is not Role.ADMIN:
            await self._guard_last_admin(target)
        now = self.clock.now()
        previous = target.role
        target.role = role
        target.token_version += 1
        await revoke_user_sessions(self.db, target.id, now=now, reason="role_changed")
        audit.record(
            self.db,
            action="admin.role_changed",
            now=now,
            actor_id=actor.id,
            target_id=target.id,
            ip=ctx.ip,
            details={"from": previous.value, "to": role.value},
        )
        await self.db.commit()
        await self.db.refresh(target)
        return target
