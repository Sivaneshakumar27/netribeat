from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import login, make_user

RR = Path(__file__).resolve().parents[1] / "fixtures" / "rr"
DS = Path(__file__).resolve().parents[1] / "fixtures" / "datasets"
S = "/api/v1/sessions"


async def up(
    client: httpx.AsyncClient, h: dict[str, str], name: str, data: bytes, **form: str
) -> dict[str, object]:
    r = await client.post(S, headers=h, files=[("files", (name, data, "text/csv"))], data=form)
    assert r.status_code == 202, r.text
    item: dict[str, object] = r.json()["items"][0]
    return item


async def test_rr_csv_and_its_json_equivalent_give_identical_results(
    client: httpx.AsyncClient, db: AsyncSession
) -> None:
    await make_user(db, email="ada@example.org")
    h = await login(client, "ada@example.org")
    csv_s = await up(client, h, "D1BLHR_RR.csv", (RR / "D1BLHR_RR.csv").read_bytes(), age="31")
    json_s = await up(client, h, "D1BLHR.json", (DS / "D1BLHR.json").read_bytes(), age="31")
    plain = [int(v) for v in (RR / "D1BLHR_RR.csv").read_text().split()]
    list_s = await up(client, h, "rr.json", json.dumps({"rr": plain}).encode(), age="31")
    results = []
    for s in (csv_s, json_s, list_s):
        assert s["status"] == "ready"
        m = (await client.get(f"{S}/{s['id']}/analysis", headers=h)).json()["metrics"]
        results.append(m["advanced"])
    a, b, c = results
    for key in ("timeDomain", "frequencyDomain", "nonlinear"):
        assert a[key] == b[key] == c[key], key
    assert a["sample"]["beats"] == 367 and a["sample"]["beatsCorrected"] == 0


async def test_reanalysis_is_persisted_and_validated(
    client: httpx.AsyncClient, db: AsyncSession
) -> None:
    await make_user(db, email="ada@example.org")
    h = await login(client, "ada@example.org")
    s = await up(client, h, "D1PMHR_RR.csv", (RR / "D1PMHR_RR.csv").read_bytes())
    url = f"{S}/{s['id']}/advanced"
    r = await client.post(
        url,
        headers=h,
        json={"sampleStartS": 600, "sampleLengthS": 300, "correction": "medium", "detrend": "none"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["metrics"]["options"]["correction"] == "medium"
    assert body["metrics"]["sample"]["startS"] == 600
    assert body["series"]["sample"]["tS"][0] > 600
    stored = (await client.get(f"{S}/{s['id']}/analysis", headers=h)).json()["metrics"]["advanced"]
    assert stored["options"]["detrend"] == "none" and stored["sample"]["startS"] == 600
    for bad in ({"correction": "magic"}, {"sampleLengthS": 5}, {"arOrder": 99}, {"unknown": 1}):
        assert (await client.post(url, headers=h, json=bad)).status_code == 400, bad


async def test_reanalysis_is_owner_only(
    client_factory: Callable[[str], httpx.AsyncClient], db: AsyncSession
) -> None:
    await make_user(db, email="ada@example.org")
    await make_user(db, email="eve@example.org")
    async with client_factory("192.0.2.1") as ada, client_factory("192.0.2.2") as eve:
        ha, he = await login(ada, "ada@example.org"), await login(eve, "eve@example.org")
        s = await up(ada, ha, "D1BLHR_RR.csv", (RR / "D1BLHR_RR.csv").read_bytes())
        r = await eve.post(f"{S}/{s['id']}/advanced", headers=he, json={"correction": "none"})
        assert r.status_code == 404


async def test_pdf_starts_with_hrv_results_page(
    client: httpx.AsyncClient, db: AsyncSession
) -> None:
    await make_user(db, email="ada@example.org")
    h = await login(client, "ada@example.org")
    await client.patch(
        "/api/v1/users/me",
        headers=h,
        json={"sex": "female", "heightCm": 180, "weightKg": 78, "hrRest": 60},
    )
    s = await up(client, h, "D1BLHR_RR.csv", (RR / "D1BLHR_RR.csv").read_bytes(), age="31")
    pdf = (await client.get(f"{S}/{s['id']}/report", headers=h)).content
    assert pdf.startswith(b"%PDF") and pdf.count(b"/Type /Page\n") + pdf.count(b"/Type /Page ") >= 2
    assert b"/Subtype /Image" in pdf  # page 1 is the rendered HRV sheet


async def test_profile_subject_fields(client: httpx.AsyncClient, db: AsyncSession) -> None:
    await make_user(db, email="ada@example.org")
    h = await login(client, "ada@example.org")
    r = await client.patch(
        "/api/v1/users/me",
        headers=h,
        json={"sex": "female", "heightCm": 180, "weightKg": 78.5, "hrRest": 60},
    )
    assert r.status_code == 200
    assert {k: r.json()[k] for k in ("sex", "heightCm", "weightKg", "hrRest")} == {
        "sex": "female",
        "heightCm": 180,
        "weightKg": 78.5,
        "hrRest": 60,
    }
    for bad in ({"heightCm": 40}, {"weightKg": 500}, {"hrRest": 10}, {"sex": "robot"}):
        assert (await client.patch("/api/v1/users/me", headers=h, json=bad)).status_code == 400


@pytest.mark.parametrize("name", ["D1PMECG_RR_fromECG.csv", "D1PMECG_RR_fromECG_trimmed.csv"])
async def test_ecg_derived_rr_files_upload(
    client: httpx.AsyncClient, db: AsyncSession, name: str
) -> None:
    await make_user(db, email="ada@example.org")
    h = await login(client, "ada@example.org")
    s = await up(client, h, name, (RR / name).read_bytes())
    assert s["status"] == "ready" and s["files"][0]["format"] == "rr_text"  # type: ignore[index]
