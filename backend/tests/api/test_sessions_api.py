from __future__ import annotations

import csv
import io
import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from netribeat.audit.models import AuditEvent
from netribeat.core.storage import MemoryStorage
from netribeat.sessions.models import Session, SessionStatus
from netribeat.users.models import HrMaxMethod
from tests.conftest import table_count
from tests.factories import login, make_admin, make_user

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "datasets"
S = "/api/v1/sessions"


def files(*names: str) -> list[tuple[str, tuple[str, bytes, str]]]:
    return [("files", (n, (FIX / n).read_bytes(), "application/octet-stream")) for n in names]


async def upload(
    client: httpx.AsyncClient, h: dict[str, str], *names: str, **form: str
) -> httpx.Response:
    return await client.post(S, headers=h, files=files(*names), data=form)


# ------------------------------------------------------------- happy path


async def test_upload_csv_analyses_and_reads_back(
    client: httpx.AsyncClient, db: AsyncSession
) -> None:
    await make_user(db, email="ada@example.org")
    h = await login(client, "ada@example.org")
    r = await upload(client, h, "D4BLHRV_BLHR.csv", type="rest", device="chest_strap_rr")
    assert r.status_code == 202, r.text
    s = r.json()["items"][0]
    assert s["status"] == "ready" and s["quality"] == "good" and s["reliable"] is True
    assert s["age"] == 18 and s["ageSource"] == "file"  # read from the CSV header
    assert s["recordedAt"].startswith("2026-09-04T16:11:54") and s["recordedAtSource"] == "file"
    assert s["files"][0]["format"] == "movesense_csv_ecg" and len(s["files"][0]["sha256"]) == 64
    assert s["avgHr"] == pytest.approx(80.7, abs=0.1)

    a = (await client.get(f"{S}/{s['id']}/analysis", headers=h)).json()["metrics"]
    assert a["hrMax"] == {
        "value": 192,
        "method": "age",
        "label": "Age-based",
        "detail": "210 − age (age 18)",
    }
    assert sum(a["timeInZonesS"].values()) > 0 and a["trainingLoad"] is not None
    assert a["timeDomain"]["rmssd"] == pytest.approx(24.1, abs=0.1)
    sig = (await client.get(f"{S}/{s['id']}/signals", headers=h)).json()["signals"]
    assert sig["ecgStrip"]["fs"] == 200.0 and len(sig["ecgStrip"]["signal"]) == 2000
    assert len(sig["hr"]["bpm"]) == len(sig["hr"]["tS"]) > 300


async def test_json_ecg_without_age_has_no_zones_until_age_given(
    client: httpx.AsyncClient, db: AsyncSession
) -> None:
    await make_user(db, email="ada@example.org")
    h = await login(client, "ada@example.org")
    s = (await upload(client, h, "D1BLECG.json")).json()["items"][0]
    assert s["status"] == "ready" and s["age"] is None and s["recordedAtSource"] == "upload_time"
    m = (await client.get(f"{S}/{s['id']}/analysis", headers=h)).json()["metrics"]
    assert m["trainingLoad"] is None and "unknown" in m["zonesUnavailableReason"]
    s2 = (
        await upload(client, h, "D1BLECG.json", age="29", recordedAt="2026-09-01T07:00:00+05:30")
    ).json()["items"][0]
    assert s2["recordedAt"].startswith("2026-09-01T01:30:00")
    m2 = (await client.get(f"{S}/{s2['id']}/analysis", headers=h)).json()["metrics"]
    assert m2["hrMax"]["value"] == 181 and m2["trainingLoad"] is not None


async def test_multiple_files_make_separate_sessions(
    client: httpx.AsyncClient, db: AsyncSession
) -> None:
    await make_user(db, email="ada@example.org")
    h = await login(client, "ada@example.org")
    r = await upload(client, h, "D1BLECG.json", "D1BLHR.json", age="29")
    items = r.json()["items"]
    assert [i["files"][0]["kind"] for i in items] == ["ecg", "rr"]
    assert len({i["id"] for i in items}) == 2
    lst = (await client.get(S, headers=h)).json()
    assert lst["total"] == 2 and lst["stats"]["sessions"] == 2 and lst["stats"]["users"] == 1


async def test_unreliable_detection_is_flagged(client: httpx.AsyncClient, db: AsyncSession) -> None:
    await make_user(db, email="ada@example.org")
    h = await login(client, "ada@example.org")
    s = (await upload(client, h, "D3BLHRV_BLHR.csv")).json()["items"][0]
    assert s["status"] == "ready" and s["reliable"] is False
    m = (await client.get(f"{S}/{s['id']}/analysis", headers=h)).json()["metrics"]
    assert m["warnings"][0].startswith("Beat detection is unreliable")


# ------------------------------------------------------------- validation


async def test_upload_rejects_unsupported_files(
    client: httpx.AsyncClient, db: AsyncSession
) -> None:
    await make_user(db, email="ada@example.org")
    h = await login(client, "ada@example.org")
    bad = [
        ("files", ("rec.hex", b"0A1B2C\n3D4E5F\n", "text/plain")),
        ("files", ("notes.csv", b"a,b\n1,2\n", "text/csv")),
        ("files", ("pic.png", b"\x89PNG", "image/png")),
    ]
    r = await client.post(S, headers=h, files=bad)
    assert r.status_code == 400
    f = r.json()["fields"]
    assert "sensor-formats.md" in f["files.0"] and "none is named RR" in f["files.1"]
    assert "not recognised" in f["files.2"]
    assert await table_count(db, "sessions") == 0
    ok_content_bad_name = (FIX / "D1BLHR.json").read_bytes()
    r = await client.post(S, headers=h, files=[("files", ("rr.exe", ok_content_bad_name, "x"))])
    assert "only .json and .csv" in r.json()["fields"]["files.0"]


async def test_upload_field_validation(client: httpx.AsyncClient, db: AsyncSession) -> None:
    await make_user(db, email="ada@example.org")
    h = await login(client, "ada@example.org")
    r = await upload(client, h, "D1BLHR.json", age="7", hrMaxManual="300", type="nap")
    assert r.status_code == 400 and {"age", "hrMaxManual", "type"} <= set(r.json()["fields"])
    r = await upload(client, h, "D1BLHR.json", recordedAt="2026-09-01T07:00:00")
    assert r.json()["fields"]["recordedAt"].startswith("Include a time zone")
    r = await client.post(S, headers=h, data={"type": "rest"})
    assert r.status_code == 400 and "files" in r.json()["fields"]


async def test_file_over_limit_is_413(
    app: FastAPI, client: httpx.AsyncClient, db: AsyncSession
) -> None:
    app.state.settings.max_upload_file_bytes = 2048
    await make_user(db, email="ada@example.org")
    h = await login(client, "ada@example.org")
    r = await upload(client, h, "D1BLHR.json")
    assert r.status_code == 413


async def test_invalid_content_fails_in_job_with_safe_message(
    client: httpx.AsyncClient, db: AsyncSession
) -> None:
    await make_user(db, email="ada@example.org")
    h = await login(client, "ada@example.org")
    broken = json.dumps({"data": [{"ecg": {"Timestamp": 1, "Samples": "nope"}}]}).encode()
    r = await client.post(S, headers=h, files=[("files", ("x.json", broken, "application/json"))])
    s = r.json()["items"][0]
    assert s["status"] == "failed" and "Samples must be a non-empty list" in s["error"]
    assert (await client.get(f"{S}/{s['id']}/analysis", headers=h)).status_code == 409


# ------------------------------------------------------------- isolation


async def test_users_cannot_reach_each_others_sessions(
    client_factory: Callable[[str], httpx.AsyncClient], db: AsyncSession
) -> None:
    await make_user(db, email="ada@example.org")
    await make_user(db, email="eve@example.org")
    async with client_factory("192.0.2.1") as ada, client_factory("192.0.2.2") as eve:
        ha, he = await login(ada, "ada@example.org"), await login(eve, "eve@example.org")
        s = (await upload(ada, ha, "D1BLHR.json")).json()["items"][0]
        sid, fid = s["id"], s["files"][0]["id"]
        for method, path in [
            ("GET", f"{S}/{sid}"),
            ("GET", f"{S}/{sid}/analysis"),
            ("GET", f"{S}/{sid}/signals"),
            ("GET", f"{S}/{sid}/report"),
            ("GET", f"{S}/{sid}/export.json"),
            ("GET", f"{S}/{sid}/export.csv?dataset=rr"),
            ("GET", f"{S}/{sid}/files/{fid}"),
            ("POST", f"{S}/{sid}/retry"),
            ("DELETE", f"{S}/{sid}"),
        ]:
            r = await eve.request(method, path, headers=he)
            assert r.status_code == 404, (method, path, r.status_code)
        lst = (await eve.get(S, headers=he, params={"userId": s["userId"]})).json()
        assert lst["total"] == 0  # a userId filter can't widen a user's scope
        r = await eve.post(S, headers=he, files=files("D1BLHR.json"), data={"userId": s["userId"]})
        assert r.status_code == 403
        assert (await ada.get(f"{S}/{sid}", headers=ha)).status_code == 200


async def test_admin_sees_all_and_uploads_for_a_user(
    client_factory: Callable[[str], httpx.AsyncClient], db: AsyncSession
) -> None:
    await make_admin(db, email="boss@example.org")
    ada = await make_user(db, email="ada@example.org")
    async with client_factory("192.0.2.1") as admin_c, client_factory("192.0.2.2") as user_c:
        ha, hu = await login(admin_c, "boss@example.org"), await login(user_c, "ada@example.org")
        r = await upload(admin_c, ha, "D1BLHR.json", userId=str(ada.id))
        s = r.json()["items"][0]
        assert s["userId"] == str(ada.id) and s["userEmail"] == "ada@example.org"
        assert (await user_c.get(f"{S}/{s['id']}", headers=hu)).status_code == 200
        lst = (await admin_c.get(S, headers=ha, params={"userId": str(ada.id)})).json()
        assert lst["total"] == 1
    events = (
        (await db.execute(select(AuditEvent).where(AuditEvent.action == "session.uploaded")))
        .scalars()
        .all()
    )
    assert events[0].target_user_id == ada.id


# ------------------------------------------------------------- exports


async def test_exports_and_pdf(client: httpx.AsyncClient, db: AsyncSession) -> None:
    await make_user(db, email="ada@example.org", first_name="Ada", last_name="Lovelace")
    h = await login(client, "ada@example.org")
    sid = (await upload(client, h, "D2BLECG.json", age="25")).json()["items"][0]["id"]

    pdf = await client.get(f"{S}/{sid}/report", headers=h)
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    assert pdf.headers["content-disposition"] == f'attachment; filename="netribeat-{sid[:8]}.pdf"'
    assert pdf.headers["cache-control"] == "no-store"

    doc = json.loads((await client.get(f"{S}/{sid}/export.json", headers=h)).content)
    assert doc["provenance"]["sourceFiles"][0]["format"] == "movesense_json_ecg"
    assert set(doc["provenance"]["provisionalRules"]) == {"P2", "P3", "P4", "P5"}
    assert doc["metrics"]["timeDomain"]["rmssd"] == pytest.approx(98.6, abs=0.2)

    rows = list(
        csv.reader(io.StringIO((await client.get(f"{S}/{sid}/export.csv", headers=h)).text))
    )
    as_dict = dict(rows[1:])
    assert rows[0] == ["metric", "value"] and as_dict["quality"] == "good"
    assert float(as_dict["timeDomain.rmssd"]) == pytest.approx(98.6, abs=0.2)
    rr = list(
        csv.reader(
            io.StringIO((await client.get(f"{S}/{sid}/export.csv?dataset=rr", headers=h)).text)
        )
    )
    assert rr[0] == ["beat", "t_s", "rr_raw_ms", "rr_corrected_ms", "artefact"] and len(rr) == 474
    assert (await client.get(f"{S}/{sid}/export.csv?dataset=secrets", headers=h)).status_code == 400

    original = await client.get(
        f"{S}/{sid}/files/" + (await client.get(f"{S}/{sid}", headers=h)).json()["files"][0]["id"],
        headers=h,
    )
    assert original.content == (FIX / "D2BLECG.json").read_bytes()


# ------------------------------------------------------------- delete, retry


async def test_delete_removes_rows_and_stored_file(
    app: FastAPI, client: httpx.AsyncClient, db: AsyncSession
) -> None:
    await make_user(db, email="ada@example.org")
    h = await login(client, "ada@example.org")
    sid = (await upload(client, h, "D1BLHR.json")).json()["items"][0]["id"]
    storage: MemoryStorage = app.state.storage
    assert len(storage.files) == 1
    assert (await client.delete(f"{S}/{sid}", headers=h)).status_code == 204
    assert storage.files == {}
    for table in ("sessions", "session_files", "analysis_results"):
        assert await table_count(db, table) == 0
    assert (await client.get(f"{S}/{sid}", headers=h)).status_code == 404


async def test_retry_only_failed_and_succeeds_after_fix(
    app: FastAPI, client: httpx.AsyncClient, db: AsyncSession
) -> None:
    await make_user(db, email="ada@example.org")
    h = await login(client, "ada@example.org")
    ready = (await upload(client, h, "D1BLHR.json")).json()["items"][0]
    assert (await client.post(f"{S}/{ready['id']}/retry", headers=h)).status_code == 409
    # Simulate a transient failure (e.g. storage outage), then a successful retry.
    storage: MemoryStorage = app.state.storage
    original_get = storage.get

    async def broken(key: str) -> bytes:
        raise RuntimeError("storage down")

    storage.get = broken  # type: ignore[method-assign]
    failed = (await upload(client, h, "D1BLHR.json")).json()["items"][0]
    assert failed["status"] == "failed" and "unexpectedly" in failed["error"]
    assert "storage down" not in failed["error"]  # internal detail never shown
    storage.get = original_get  # type: ignore[method-assign]
    retried = (await client.post(f"{S}/{failed['id']}/retry", headers=h)).json()
    assert retried["status"] == "ready" and retried["attempts"] == 2


async def test_processing_is_idempotent(
    app: FastAPI, client: httpx.AsyncClient, db: AsyncSession
) -> None:
    from netribeat.sessions.processing import process_session

    await make_user(db, email="ada@example.org")
    h = await login(client, "ada@example.org")
    sid = (await upload(client, h, "D1BLHR.json")).json()["items"][0]["id"]
    import uuid as _uuid

    await process_session(
        app.state.sessionmaker, app.state.storage, app.state.clock, _uuid.UUID(sid)
    )
    row = (await db.execute(select(Session).where(Session.id == _uuid.UUID(sid)))).scalar_one()
    await db.refresh(row)
    assert row.status is SessionStatus.READY and row.attempts == 1  # second run was a no-op


# ------------------------------------------------------------- HRmax settings


async def test_hr_max_change_recomputes_only_this_users_sessions(
    client_factory: Callable[[str], httpx.AsyncClient], db: AsyncSession
) -> None:
    await make_user(db, email="ada@example.org")
    await make_user(db, email="eve@example.org")
    async with client_factory("192.0.2.1") as ada, client_factory("192.0.2.2") as eve:
        ha, he = await login(ada, "ada@example.org"), await login(eve, "eve@example.org")
        sa = (await upload(ada, ha, "D4BLHRV_BLHR.csv")).json()["items"][0]["id"]
        se = (await upload(eve, he, "D4BLHRV_BLHR.csv")).json()["items"][0]["id"]
        before_a = (await ada.get(f"{S}/{sa}/analysis", headers=ha)).json()["metrics"]
        before_e = (await eve.get(f"{S}/{se}/analysis", headers=he)).json()["metrics"]

        bad = await ada.put(
            "/api/v1/users/me/hr-max", headers=ha, json={"method": "manual", "manualValue": 99}
        )
        assert bad.status_code == 400 and "manualValue" in bad.json()["fields"]
        r = await ada.put(
            "/api/v1/users/me/hr-max", headers=ha, json={"method": "manual", "manualValue": 130}
        )
        assert r.status_code == 200 and r.json()["recomputedSessions"] == 1
        assert r.json()["effective"]["value"] == 130

        after_a = (await ada.get(f"{S}/{sa}/analysis", headers=ha)).json()["metrics"]
        after_e = (await eve.get(f"{S}/{se}/analysis", headers=he)).json()["metrics"]
        assert (
            after_a["hrMax"]["value"] == 130 and after_a["trainingLoad"] > before_a["trainingLoad"]
        )
        assert after_e == before_e  # another user's results are untouched
        assert after_a["timeDomain"] == before_a["timeDomain"]  # no ECG reprocessing

        peak = await ada.put("/api/v1/users/me/hr-max", headers=ha, json={"method": "peak"})
        assert peak.json()["effective"]["value"] == round(after_a["hr"]["max"])


async def test_peak_needs_reliable_sessions_and_admin_can_set(
    client_factory: Callable[[str], httpx.AsyncClient], db: AsyncSession
) -> None:
    await make_admin(db, email="boss@example.org")
    ada = await make_user(db, email="ada@example.org", age=30)
    async with client_factory("192.0.2.1") as admin_c, client_factory("192.0.2.2") as user_c:
        ha, hu = await login(admin_c, "boss@example.org"), await login(user_c, "ada@example.org")
        r = await user_c.put("/api/v1/users/me/hr-max", headers=hu, json={"method": "peak"})
        assert r.status_code == 400
        assert (await user_c.get("/api/v1/users/me/hr-max", headers=hu)).json()["options"][0][
            "value"
        ] == 180
        url = f"/api/v1/admin/users/{ada.id}/hr-max"
        assert (await user_c.put(url, headers=hu, json={"method": "age"})).status_code == 403
        r = await admin_c.put(url, headers=ha, json={"method": "manual", "manualValue": 190})
        assert r.status_code == 200 and r.json()["method"] == "manual"
    await db.refresh(ada)
    assert ada.hr_max_method is HrMaxMethod.MANUAL


async def test_entered_age_overrides_file_age_with_warning(
    client: httpx.AsyncClient, db: AsyncSession
) -> None:
    await make_user(db, email="ada@example.org")
    h = await login(client, "ada@example.org")
    s = (await upload(client, h, "D4BLHRV_BLHR.csv", age="29")).json()["items"][0]
    assert s["age"] == 29 and s["ageSource"] == "form"
    m = (await client.get(f"{S}/{s['id']}/analysis", headers=h)).json()["metrics"]
    assert m["hrMax"]["value"] == 181
    assert any("differs from the age in the file header (18)" in w for w in m["warnings"])


async def test_no_ecg_session_has_no_hr_or_load(
    client: httpx.AsyncClient, db: AsyncSession
) -> None:
    await make_user(db, email="ada@example.org")
    h = await login(client, "ada@example.org")
    s = (await upload(client, h, "D3BLHRV_BLHR.csv")).json()["items"][0]
    assert s["quality"] == "no_ecg" and s["avgHr"] is None and s["trainingLoad"] is None
    m = (await client.get(f"{S}/{s['id']}/analysis", headers=h)).json()["metrics"]
    assert m["zonesUnavailableReason"] == "No heart-rate series"


async def test_windows_encoded_files_upload_and_analyse(
    client: httpx.AsyncClient, db: AsyncSession
) -> None:
    await make_user(db, email="ada@example.org")
    h = await login(client, "ada@example.org")
    text = (FIX / "D1BLHR.json").read_text(encoding="utf-8")
    payload = [
        ("files", ("bom.json", b"\xef\xbb\xbf" + text.encode(), "application/json")),
        ("files", ("utf16.json", text.encode("utf-16"), "application/json")),
    ]
    r = await client.post(S, headers=h, files=payload)
    assert r.status_code == 202, r.text
    assert [s["status"] for s in r.json()["items"]] == ["ready", "ready"]
