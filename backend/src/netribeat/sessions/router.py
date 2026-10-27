"""/api/v1/sessions (upload, list, results, report, exports) and max-HR settings."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, File, Form, Query, Response, UploadFile, status

from netribeat.auth.deps import AdminUser, ClockDep, ContextDep, CurrentUser, DbDep
from netribeat.auth.models import User
from netribeat.core.api_model import error_responses
from netribeat.core.errors import Conflict, NotFound
from netribeat.reports import exports, pdf
from netribeat.sessions import service
from netribeat.sessions.models import Recording
from netribeat.sessions.schemas import (
    AnalysisOut,
    FileInfo,
    HrMaxSettingsIn,
    HrMaxSettingsOut,
    SessionList,
    SessionOut,
    SessionStats,
    SessionSummary,
    SignalsOut,
    UploadResult,
)

router = APIRouter(prefix="/sessions", tags=["Sessions"])
hrmax_router = APIRouter(tags=["Max HR"])
E = error_responses(400, 401, 404)


def _summary(rec: Recording, owner: User | None) -> dict[str, object]:
    return {
        "id": rec.id,
        "user_id": rec.user_id,
        "user_email": owner.email if owner else None,
        "user_name": owner.display_name if owner else "Deleted user",
        "type": rec.type,
        "recorded_at": rec.recorded_at,
        "duration_s": rec.duration_s,
        "status": rec.status,
        "quality": None,
        "reliable": True if rec.status == "ready" else None,
        "avg_hr": rec.avg_hr,
        "max_hr": rec.max_hr,
        "min_hr": rec.min_hr,
        "rmssd": None,
        "training_load": rec.training_load,
        "movement_load": rec.movement_load,
        "file_name": rec.file_name,
    }


def _detail(rec: Recording, owner: User | None) -> SessionOut:
    return SessionOut(
        **_summary(rec, owner),
        age=rec.age,
        age_source=rec.age_source,
        recorded_at_source=rec.recorded_at_source,
        device=rec.device,
        notes=rec.notes,
        hr_max_manual=rec.hr_max_manual,
        files=[
            FileInfo(
                id=rec.id,
                name=rec.file_name,
                kind="rr",
                format="synapse_hex",
                size_bytes=rec.file_size,
            )
        ],
        artefact_count=None,
        artefact_pct=None,
        hrv_window_s=[],
        error=rec.error,
        attempts=rec.attempts,
        created_at=rec.created_at,
        processed_at=rec.processed_at,
    )


async def _with_owner(db: DbDep, rec: Recording) -> SessionOut:
    return _detail(rec, await db.get(User, rec.user_id))


async def _ready(db: DbDep, user: User, session_id: uuid.UUID) -> Recording:
    rec = await service.get(db, user, session_id, full=True)
    if rec.status != "ready":
        raise Conflict("The session has no results yet", code="not_ready")
    return rec


def _download(content: bytes, media_type: str, filename: str) -> Response:
    return Response(
        content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("", response_model=SessionList, responses=E, summary="List visible sessions")
async def list_sessions(
    user: CurrentUser,
    db: DbDep,
    q: Annotated[str | None, Query(max_length=100)] = None,
    user_id: Annotated[uuid.UUID | None, Query(alias="userId")] = None,
    status_: Annotated[str | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SessionList:
    rows, total, stats = await service.list_sessions(
        db, user, q=q, user_id=user_id, status=status_, limit=limit, offset=offset
    )
    owners = await service.owners(db, rows)
    return SessionList(
        items=[SessionSummary(**_summary(r, owners.get(r.user_id))) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
        stats=SessionStats(**stats, avg_rmssd=None),
    )


@router.post(
    "",
    response_model=UploadResult,
    status_code=status.HTTP_201_CREATED,
    responses=error_responses(400, 401, 403, 413),
    summary="Upload Synapse hex files; each session in a file is analysed",
)
async def upload(
    user: CurrentUser,
    db: DbDep,
    clock: ClockDep,
    ctx: ContextDep,
    files: Annotated[list[UploadFile], File(description="Synapse sensor hex files (.txt)")],
    type_: Annotated[str, Form(alias="type", max_length=20)] = "training",
    device: Annotated[str, Form(max_length=40)] = "synapse",
    recorded_at: Annotated[datetime | None, Form(alias="recordedAt")] = None,
    age: Annotated[int | None, Form(ge=8, le=100)] = None,
    hr_max_manual: Annotated[int | None, Form(alias="hrMaxManual", ge=100, le=230)] = None,
    notes: Annotated[str | None, Form(max_length=500)] = None,
    user_id: Annotated[uuid.UUID | None, Form(alias="userId")] = None,
) -> UploadResult:
    data = [(f.filename or "recording.txt", await f.read()) for f in files]
    form = service.UploadForm(
        type=type_,
        device=device,
        recorded_at=recorded_at,
        age=age,
        hr_max_manual=hr_max_manual,
        notes=notes,
        user_id=user_id,
    )
    created = await service.upload(db, clock, actor=user, files=data, form=form, ctx=ctx)
    owners = await service.owners(db, created)
    return UploadResult(items=[_detail(r, owners.get(r.user_id)) for r in created])


@router.get("/{session_id}", response_model=SessionOut, responses=E, summary="One session")
async def get_session(session_id: uuid.UUID, user: CurrentUser, db: DbDep) -> SessionOut:
    return await _with_owner(db, await service.get(db, user, session_id))


@router.get("/{session_id}/analysis", response_model=AnalysisOut, responses=E, summary="Metrics")
async def get_analysis(session_id: uuid.UUID, user: CurrentUser, db: DbDep) -> AnalysisOut:
    rec = await _ready(db, user, session_id)
    return AnalysisOut(session_id=rec.id, metrics=rec.metrics or {})


@router.get("/{session_id}/signals", response_model=SignalsOut, responses=E, summary="Series")
async def get_signals(session_id: uuid.UUID, user: CurrentUser, db: DbDep) -> SignalsOut:
    rec = await _ready(db, user, session_id)
    return SignalsOut(session_id=rec.id, signals=rec.signals or {})


@router.post("/{session_id}/advanced", responses=E, summary="Advanced HRV (not for hex files)")
async def advanced(session_id: uuid.UUID, user: CurrentUser, db: DbDep) -> Response:
    await service.get(db, user, session_id)
    raise Conflict("Advanced HRV is not available for sensor hex files", code="not_available")


@router.get("/{session_id}/report", responses=E, summary="PDF report")
async def report(session_id: uuid.UUID, user: CurrentUser, db: DbDep, clock: ClockDep) -> Response:
    rec = await _ready(db, user, session_id)
    owner = await db.get(User, rec.user_id)
    label = owner.display_name if owner else "Deleted user"
    content = pdf.render(rec, label, clock.now())
    return _download(content, "application/pdf", f"netribeat-session-{str(rec.id)[:8]}.pdf")


@router.get("/{session_id}/export.json", responses=E, summary="All results as JSON")
async def export_json(
    session_id: uuid.UUID, user: CurrentUser, db: DbDep, clock: ClockDep
) -> Response:
    rec = await _ready(db, user, session_id)
    return _download(
        exports.to_json(rec, clock.now()),
        "application/json",
        f"netribeat-session-{str(rec.id)[:8]}.json",
    )


@router.get("/{session_id}/export.csv", responses=E, summary="Metrics or a series as CSV")
async def export_csv(
    session_id: uuid.UUID,
    user: CurrentUser,
    db: DbDep,
    dataset: Annotated[str, Query(pattern="^(metrics|hr|rr|rms|psd)$")] = "metrics",
) -> Response:
    if dataset == "psd":
        raise NotFound("There is no spectrum for sensor hex files")
    rec = await _ready(db, user, session_id)
    return _download(
        exports.to_csv(rec, dataset),
        "text/csv",
        f"netribeat-session-{str(rec.id)[:8]}-{dataset}.csv",
    )


@router.get("/{session_id}/files/{file_id}", responses=E, summary="The original uploaded file")
async def original(
    session_id: uuid.UUID, file_id: uuid.UUID, user: CurrentUser, db: DbDep
) -> Response:
    rec = await service.get(db, user, session_id, full=True)
    if file_id != rec.id:
        raise NotFound()
    return _download(rec.file_data, "text/plain", rec.file_name.replace('"', ""))


@router.delete(
    "/{session_id}", status_code=status.HTTP_204_NO_CONTENT, responses=E, summary="Delete"
)
async def delete_session(
    session_id: uuid.UUID, user: CurrentUser, db: DbDep, clock: ClockDep, ctx: ContextDep
) -> Response:
    rec = await service.get(db, user, session_id)
    await service.delete(db, clock, user, rec, ctx)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{session_id}/retry", response_model=SessionOut, responses=E, summary="Analyse again")
async def retry(session_id: uuid.UUID, user: CurrentUser, db: DbDep, clock: ClockDep) -> SessionOut:
    rec = await service.get(db, user, session_id, full=True)
    owner = await db.get(User, rec.user_id)
    if owner is None:
        raise NotFound()
    await service.reanalyse(db, clock, rec, owner)
    return _detail(rec, owner)


# ------------------------------------------------------------------ max HR


@hrmax_router.get("/users/me/hr-max", response_model=HrMaxSettingsOut, summary="My max HR")
async def my_hr_max(user: CurrentUser, db: DbDep) -> HrMaxSettingsOut:
    return await service.hr_max_settings(db, user)


@hrmax_router.put(
    "/users/me/hr-max",
    response_model=HrMaxSettingsOut,
    responses=error_responses(400, 401),
    summary="Set my max HR method; recalculates my sessions",
)
async def set_my_hr_max(
    body: HrMaxSettingsIn, user: CurrentUser, db: DbDep, clock: ClockDep, ctx: ContextDep
) -> HrMaxSettingsOut:
    return await service.set_hr_max(
        db,
        clock,
        actor=user,
        target=user,
        method=body.method,
        manual_value=body.manual_value,
        ctx=ctx,
    )


async def _target(db: DbDep, user_id: uuid.UUID) -> User:
    target = await db.get(User, user_id)
    if target is None:
        raise NotFound("User not found")
    return target


@hrmax_router.get(
    "/admin/users/{user_id}/hr-max", response_model=HrMaxSettingsOut, summary="A user's max HR"
)
async def user_hr_max(user_id: uuid.UUID, admin: AdminUser, db: DbDep) -> HrMaxSettingsOut:
    return await service.hr_max_settings(db, await _target(db, user_id))


@hrmax_router.put(
    "/admin/users/{user_id}/hr-max",
    response_model=HrMaxSettingsOut,
    responses=error_responses(400, 401, 403, 404),
    summary="Set a user's max HR method; recalculates their sessions",
)
async def set_user_hr_max(
    user_id: uuid.UUID,
    body: HrMaxSettingsIn,
    admin: AdminUser,
    db: DbDep,
    clock: ClockDep,
    ctx: ContextDep,
) -> HrMaxSettingsOut:
    return await service.set_hr_max(
        db,
        clock,
        actor=admin,
        target=await _target(db, user_id),
        method=body.method,
        manual_value=body.manual_value,
        ctx=ctx,
    )
