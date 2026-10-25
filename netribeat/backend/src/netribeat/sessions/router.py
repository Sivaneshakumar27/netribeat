"""/api/v1/sessions — upload, list, read, export, delete, retry — plus HRmax settings."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, File, Form, Query, Response, UploadFile, status

from netribeat.api_model import error_responses
from netribeat.auth.deps import AdminUser, ClockDep, ContextDep, CurrentUser, DbDep
from netribeat.errors import NotFound, PayloadTooLarge, ValidationFailed
from netribeat.reports import exports, pdf
from netribeat.sessions.deps import SessionServiceDep
from netribeat.sessions.models import Device, Session, SessionFile, SessionStatus, SessionType
from netribeat.sessions.schemas import (
    AdvancedOptionsIn,
    AdvancedOut,
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
from netribeat.sessions.service import ListFilter, SessionService, UploadedFile, UploadForm
from netribeat.users import repository as users_repo
from netribeat.users.models import User

router = APIRouter(prefix="/sessions", tags=["Sessions"])
hrmax_router = APIRouter(tags=["Settings"])
E = error_responses(400, 401, 404)


def summary(s: Session, owner: User) -> dict[str, object]:
    return {
        "id": s.id,
        "user_id": s.user_id,
        "user_email": owner.email,
        "user_name": owner.display_name,
        "type": s.type,
        "recorded_at": s.recorded_at,
        "duration_s": s.duration_s,
        "status": s.status,
        "quality": s.quality,
        "reliable": s.reliable,
        "avg_hr": s.avg_hr,
        "max_hr": s.max_hr,
        "rmssd": s.rmssd,
        "training_load": s.training_load,
        "file_name": s.file_name,
    }


async def detail(service: SessionService, s: Session) -> SessionOut:
    owner = await service.owner_of(s)
    files = await service.files(s.id)
    return SessionOut.model_validate(
        {
            **summary(s, owner),
            "age": s.age,
            "age_source": s.age_source,
            "recorded_at_source": s.recorded_at_source,
            "device": s.device,
            "notes": s.notes,
            "hr_max_manual": s.hr_max_manual,
            "files": [FileInfo.model_validate(f) for f in files],
            "artefact_count": s.artefact_count,
            "artefact_pct": s.artefact_pct,
            "hrv_window_s": [0.0, 300.0],
            "error": s.error,
            "attempts": s.attempts,
            "created_at": s.created_at,
            "processed_at": s.processed_at,
        }
    )


def download(content: bytes, media_type: str, filename: str) -> Response:
    return Response(
        content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )


@router.get(
    "",
    response_model=SessionList,
    responses=E,
    summary="List sessions (yours; admins see everyone's and can filter by user)",
)
async def list_sessions(
    user: CurrentUser,
    service: SessionServiceDep,
    q: Annotated[str | None, Query(max_length=100)] = None,
    user_id: Annotated[uuid.UUID | None, Query(alias="userId")] = None,
    status_: Annotated[SessionStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> SessionList:
    rows, total, stats = await service.list(
        user, ListFilter(q=q, user_id=user_id, status=status_), limit=limit, offset=offset
    )
    return SessionList(
        items=[SessionSummary.model_validate(summary(s, o)) for s, o in rows],
        total=total,
        limit=limit,
        offset=offset,
        stats=SessionStats(**stats),
    )


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=UploadResult,
    responses=error_responses(400, 401, 403, 404, 413),
    summary="Upload .json / .csv recordings (one session per file, analysed in the background)",
)
async def upload(
    user: CurrentUser,
    service: SessionServiceDep,
    ctx: ContextDep,
    files: Annotated[list[UploadFile], File(description="Movesense JSON (ECG or RR) or CSV ECG")],
    type_: Annotated[SessionType, Form(alias="type")] = SessionType.TRAINING,
    device: Annotated[Device, Form()] = Device.CHEST_STRAP_RR,
    recorded_at: Annotated[datetime | None, Form(alias="recordedAt")] = None,
    age: Annotated[int | None, Form(ge=8, le=100)] = None,
    hr_max_manual: Annotated[int | None, Form(alias="hrMaxManual", ge=100, le=230)] = None,
    notes: Annotated[str | None, Form(max_length=500)] = None,
    user_id: Annotated[uuid.UUID | None, Form(alias="userId")] = None,
) -> UploadResult:
    limit = service.s.max_upload_file_bytes
    uploaded: list[UploadedFile] = []
    for f in files:
        data = await f.read(limit + 1)
        if len(data) > limit:
            raise PayloadTooLarge(f"{f.filename or 'A file'} is larger than 50 MB")
        uploaded.append(UploadedFile(name=f.filename or "recording", data=data))
    if recorded_at is not None and recorded_at.tzinfo is None:
        raise ValidationFailed(
            fields={"recordedAt": "Include a time zone, e.g. 2026-09-28T07:12:00+05:30"}
        )
    sessions = await service.upload(
        user,
        uploaded,
        UploadForm(
            type=type_,
            device=device,
            recorded_at=recorded_at,
            age=age,
            hr_max_manual=hr_max_manual,
            notes=(notes or None),
            user_id=user_id,
        ),
        ctx,
    )
    return UploadResult(items=[await detail(service, s) for s in sessions])


@router.get(
    "/{session_id}", response_model=SessionOut, responses=E, summary="Session details and status"
)
async def get_session(
    session_id: uuid.UUID, user: CurrentUser, service: SessionServiceDep
) -> SessionOut:
    return await detail(service, await service.owned(user, session_id))


@router.get(
    "/{session_id}/analysis",
    response_model=AnalysisOut,
    responses=error_responses(401, 404, 409),
    summary="Stored analysis metrics",
)
async def get_analysis(
    session_id: uuid.UUID, user: CurrentUser, service: SessionServiceDep
) -> AnalysisOut:
    _, result = await service.result(user, session_id)
    return AnalysisOut(session_id=session_id, metrics=result.metrics)


@router.get(
    "/{session_id}/signals",
    response_model=SignalsOut,
    responses=error_responses(401, 404, 409),
    summary="Chart series (1 Hz HR, RR, ECG strip, per-minute)",
)
async def get_signals(
    session_id: uuid.UUID, user: CurrentUser, service: SessionServiceDep
) -> SignalsOut:
    _, result = await service.result(user, session_id)
    return SignalsOut(session_id=session_id, signals=result.signals)


@router.post(
    "/{session_id}/advanced",
    response_model=AdvancedOut,
    responses=error_responses(400, 401, 404, 409),
    summary="Re-run the advanced HRV analysis (sample, artefact correction, detrending, spectra)",
)
async def reanalyse_advanced(
    session_id: uuid.UUID,
    body: AdvancedOptionsIn,
    user: CurrentUser,
    service: SessionServiceDep,
    ctx: ContextDep,
) -> AdvancedOut:
    result = await service.reanalyse_advanced(user, session_id, body.model_dump(), ctx)
    return AdvancedOut(
        session_id=session_id,
        metrics=result.metrics["advanced"],
        series=result.signals["advanced"],
    )


@router.get(
    "/{session_id}/report",
    responses=error_responses(401, 404, 409),
    response_class=Response,
    summary="PDF report",
)
async def get_report(
    session_id: uuid.UUID, user: CurrentUser, service: SessionServiceDep, clock: ClockDep
) -> Response:
    session, result = await service.result(user, session_id)
    owner = await service.owner_of(session)
    files = list(await service.files(session.id))
    hr_max = (result.metrics.get("hrMax") or {}).get("value")
    subject = {
        "sex": owner.sex.value if owner.sex else None,
        "age": session.age,
        "height_cm": owner.height_cm,
        "weight_kg": owner.weight_kg,
        "hr_rest": owner.hr_rest,
        "hr_max": hr_max,
    }
    content = pdf.render(session, result, files, owner.display_name, clock.now(), subject)
    return download(content, "application/pdf", f"netribeat-{str(session_id)[:8]}.pdf")


@router.get(
    "/{session_id}/export.json",
    responses=error_responses(401, 404, 409),
    response_class=Response,
    summary="Full JSON export with provenance",
)
async def export_json(
    session_id: uuid.UUID, user: CurrentUser, service: SessionServiceDep, clock: ClockDep
) -> Response:
    session, result = await service.result(user, session_id)
    files = list(await service.files(session.id))
    return download(
        exports.to_json(session, result, files, clock.now()),
        "application/json",
        f"netribeat-{str(session_id)[:8]}.json",
    )


@router.get(
    "/{session_id}/export.csv",
    responses=error_responses(400, 401, 404, 409),
    response_class=Response,
    summary="CSV export: metrics, hr (1 Hz), rr (beats) or psd",
)
async def export_csv(
    session_id: uuid.UUID,
    user: CurrentUser,
    service: SessionServiceDep,
    dataset: Annotated[str, Query(pattern="^(metrics|hr|rr|psd)$")] = "metrics",
) -> Response:
    session, result = await service.result(user, session_id)
    return download(
        exports.to_csv(session, result, dataset),
        "text/csv; charset=utf-8",
        f"netribeat-{str(session_id)[:8]}-{dataset}.csv",
    )


@router.get(
    "/{session_id}/files/{file_id}",
    responses=E,
    response_class=Response,
    summary="Download the original uploaded file",
)
async def get_original(
    session_id: uuid.UUID, file_id: uuid.UUID, user: CurrentUser, service: SessionServiceDep
) -> Response:
    f, data = await service.original_file(user, session_id, file_id)
    ext = ".json" if f.name.lower().endswith(".json") else ".csv"
    return download(
        data, "application/octet-stream", f"netribeat-{str(session_id)[:8]}-original{ext}"
    )


@router.delete(
    "/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=E,
    summary="Delete a session, its results and its stored file",
)
async def delete_session(
    session_id: uuid.UUID, user: CurrentUser, service: SessionServiceDep, ctx: ContextDep
) -> Response:
    await service.delete(user, session_id, ctx)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{session_id}/retry",
    response_model=SessionOut,
    responses=error_responses(401, 404, 409),
    summary="Re-run a failed analysis",
)
async def retry_session(
    session_id: uuid.UUID, user: CurrentUser, service: SessionServiceDep, ctx: ContextDep
) -> SessionOut:
    return await detail(service, await service.retry(user, session_id, ctx))


# ------------------------------------------------------------------ HRmax settings


@hrmax_router.get(
    "/users/me/hr-max",
    response_model=HrMaxSettingsOut,
    responses=E,
    summary="My max-HR setting and the value each method gives",
)
async def my_hr_max(user: CurrentUser, service: SessionServiceDep) -> HrMaxSettingsOut:
    return HrMaxSettingsOut.model_validate(await service.hr_max_settings(user))


@hrmax_router.put(
    "/users/me/hr-max",
    response_model=HrMaxSettingsOut,
    responses=E,
    summary="Change my max-HR method; recomputes zones and load for my sessions only",
)
async def set_my_hr_max(
    body: HrMaxSettingsIn, user: CurrentUser, service: SessionServiceDep, ctx: ContextDep
) -> HrMaxSettingsOut:
    out = await service.set_hr_max(
        user, user, method=body.method, manual_value=body.manual_value, ctx=ctx
    )
    return HrMaxSettingsOut.model_validate(out)


async def _target(db: DbDep, user_id: uuid.UUID) -> User:
    target = await users_repo.get_by_id(db, user_id)
    if target is None:
        raise NotFound("User not found")
    return target


@hrmax_router.get(
    "/admin/users/{user_id}/hr-max",
    response_model=HrMaxSettingsOut,
    responses=error_responses(401, 403, 404),
    summary="A user's max-HR setting",
)
async def user_hr_max(
    user_id: uuid.UUID, admin: AdminUser, db: DbDep, service: SessionServiceDep
) -> HrMaxSettingsOut:
    return HrMaxSettingsOut.model_validate(
        await service.hr_max_settings(await _target(db, user_id))
    )


@hrmax_router.put(
    "/admin/users/{user_id}/hr-max",
    response_model=HrMaxSettingsOut,
    responses=error_responses(400, 401, 403, 404),
    summary="Set a user's max-HR method",
)
async def set_user_hr_max(
    user_id: uuid.UUID,
    body: HrMaxSettingsIn,
    admin: AdminUser,
    db: DbDep,
    service: SessionServiceDep,
    ctx: ContextDep,
) -> HrMaxSettingsOut:
    out = await service.set_hr_max(
        admin,
        await _target(db, user_id),
        method=body.method,
        manual_value=body.manual_value,
        ctx=ctx,
    )
    return HrMaxSettingsOut.model_validate(out)


__all__ = ["SessionFile", "hrmax_router", "router"]
