"""PDF report from stored results (ReportLab). No formula is recomputed here."""

from __future__ import annotations

import io
from datetime import datetime
from typing import Any

from reportlab.graphics.charts.lineplots import LinePlot
from reportlab.graphics.shapes import Drawing, Line, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from netribeat.reports.exports import provenance

# Reports take any objects with the expected attributes (the analysis models plug in later).
type Session = Any
type AnalysisResult = Any
type SessionFile = Any

ACCENT = colors.HexColor("#b4460a")
MUTED = colors.HexColor("#5c5852")
ZONE_LABELS = [
    ("belowZ1", "Below Z1 (< 50 %)"),
    ("z1", "Z1 50-60 %"),
    ("z2", "Z2 60-70 %"),
    ("z3", "Z3 70-80 %"),
    ("z4", "Z4 80-90 %"),
    ("z5", "Z5 >= 90 %"),
]
# Helvetica (a built-in PDF font) lacks some typographic symbols.
_ASCII = str.maketrans(
    {
        "−": "-",
        "×": "x",
        "≥": ">=",
        "≤": "<=",
        "–": "-",
        "—": "-",
        "Σ": "sum",
        "√": "sqrt",
        "·": "*",
        "…": "...",
        "²": "^2",
        "’": "'",
    }
)


def _t(s: Any) -> str:
    return (
        ("" if s is None else str(s)).translate(_ASCII).replace("&", "&amp;").replace("<", "&lt;")
    )


def _n(v: Any, nd: int = 1, unit: str = "") -> str:
    if v is None:
        return "n/a"
    try:
        return f"{float(v):.{nd}f}{(' ' + unit) if unit else ''}"
    except (TypeError, ValueError):
        return _t(v)


def _table(rows: list[list[str]], widths: list[float] | None = None) -> Table:
    t = Table(rows, colWidths=widths, hAlign="LEFT")
    t.setStyle(
        TableStyle(
            [
                ("FONT", (0, 0), (-1, -1), "Helvetica", 8.5),
                ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8.5),
                ("TEXTCOLOR", (0, 0), (-1, 0), MUTED),
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, colors.lightgrey),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8f7f4")]),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    return t


def _line_chart(
    xs: list[float], ys: list[float], title: str, ylabel: str, marks: list[float] | None = None
) -> Drawing:
    w, h = 170 * mm, 55 * mm
    d = Drawing(w, h)
    if len(xs) < 2:
        d.add(String(0, h / 2, f"{title}: no data", fontName="Helvetica", fontSize=8))
        return d
    step = max(1, len(xs) // 1500)  # keep the PDF small
    lp = LinePlot()
    lp.x, lp.y, lp.width, lp.height = 30, 15, int(w - 40), int(h - 30)
    lp.data = [list(zip(xs[::step], ys[::step], strict=False))]
    lp.lines[0].strokeColor = ACCENT
    lp.lines[0].strokeWidth = 0.8
    lp.xValueAxis.labels.fontSize = 6.5
    lp.yValueAxis.labels.fontSize = 6.5
    d.add(lp)
    if marks:
        x0, x1 = min(xs), max(xs)
        for mk in marks:
            px = lp.x + (mk - x0) / ((x1 - x0) or 1) * lp.width
            d.add(
                Line(
                    px,
                    lp.y + lp.height - 6,
                    px,
                    lp.y + lp.height,
                    strokeColor=colors.red,
                    strokeWidth=0.6,
                )
            )
    d.add(String(30, h - 8, _t(f"{title} ({ylabel})"), fontName="Helvetica-Bold", fontSize=8))
    return d


def render(
    session: Session,
    result: AnalysisResult,
    files: list[SessionFile],
    owner_label: str,
    generated_at: datetime,
    subject: dict[str, Any] | None = None,
) -> bytes:
    """Page 1: the HRV results sheet (Kubios layout). Following pages: NetriBeat results."""
    m, sig = result.metrics, result.signals
    styles = getSampleStyleSheet()
    h1 = ParagraphStyle(
        "h1", parent=styles["Heading1"], fontName="Helvetica-Bold", fontSize=16, spaceAfter=2
    )
    h2 = ParagraphStyle(
        "h2",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=11,
        textColor=ACCENT,
        spaceBefore=8,
        spaceAfter=3,
    )
    body = ParagraphStyle(
        "b", parent=styles["BodyText"], fontName="Helvetica", fontSize=8.5, leading=11
    )
    warn = ParagraphStyle("w", parent=body, textColor=colors.HexColor("#a3271b"))
    out: list[Any] = []
    if m.get("advanced"):
        from netribeat.reports.hrv_page import render_png

        png = render_png(
            title_sample="sample 1",
            subject=subject or {},
            recorded_at=session.recorded_at,
            file_name=session.file_name,
            adv=m["advanced"],
            series=sig.get("advanced", {}),
            generated_at=generated_at,
        )
        page_h = A4[1] - 24 * mm  # fits the frame (margins + 6 pt frame padding)
        page_w = page_h * 8.27 / 11.69  # keep the A4 aspect ratio of the rendered sheet
        out += [Image(io.BytesIO(png), width=page_w, height=page_h), PageBreak()]
    out += [
        Paragraph("NetriBeat session report", h1),
        Paragraph(
            _t(
                f"{session.type.value.title()} session · {owner_label} · recorded "
                f"{session.recorded_at:%Y-%m-%d %H:%M} UTC"
            ),
            body,
        ),
        Spacer(1, 4),
    ]
    rel = m.get("reliability", {})
    coverage = (rel.get("beatCoverage") or 0) * 100
    out.append(
        _table(
            [
                [
                    "Session id",
                    "Quality",
                    "Beat detection",
                    "Duration",
                    "Age at recording",
                    "Device",
                ],
                [
                    str(session.id)[:8],
                    _t(m.get("quality")),
                    "reliable"
                    if rel.get("reliable")
                    else f"UNRELIABLE ({coverage:.0f} % coverage)",
                    _n(session.duration_s, 0, "s"),
                    _t(session.age or "unknown"),
                    _t(session.device.value),
                ],
            ]
        )
    )
    if m.get("warnings"):
        out.append(Paragraph("Warnings", h2))
        out.extend(Paragraph("• " + _t(w_), warn) for w_ in m["warnings"])

    out.append(Paragraph("Heart rate and zones", h2))
    hr, hm = m.get("hr", {}), m.get("hrMax") or {}
    out.append(
        _table(
            [
                [
                    "Min HR",
                    "Avg HR",
                    "Max HR",
                    "HRmax used",
                    "Source",
                    "Training load (Edwards TRIMP)",
                ],
                [
                    _n(hr.get("min"), 1, "bpm"),
                    _n(hr.get("avg"), 1, "bpm"),
                    _n(hr.get("max"), 1, "bpm"),
                    _n(hm.get("value"), 0, "bpm"),
                    _t(hm.get("label") or m.get("zonesUnavailableReason")),
                    _n(m.get("trainingLoad"), 1, "AU"),
                ],
            ]
        )
    )
    tz = m.get("timeInZonesS")
    if tz:
        out.append(Spacer(1, 3))
        zone_rows = [["Zone", "Time (min)"]] + [
            [lbl, _n(tz.get(k, 0) / 60, 1)] for k, lbl in ZONE_LABELS
        ]
        out.append(_table(zone_rows, [60 * mm, 30 * mm]))
    hrs = sig.get("hr", {})
    out.append(_line_chart(hrs.get("tS", []), hrs.get("bpm", []), "Heart rate over time", "bpm"))

    out.append(Paragraph("Beats and artefact correction", h2))
    b = m.get("beats", {})
    out.append(
        _table(
            [
                [
                    "R-peaks detected",
                    "RR intervals",
                    "Artefacts corrected",
                    "Artefact %",
                    "Beat coverage",
                ],
                [
                    _t(b.get("detected")),
                    _t(b.get("rrIntervals")),
                    _t(b.get("artefacts")),
                    _n(b.get("artefactPct"), 2, "%"),
                    _n(coverage, 0, "%"),
                ],
            ]
        )
    )
    strip = sig.get("ecgStrip")
    if strip and strip.get("signal"):
        fs = strip["fs"]
        xs = [i / fs for i in range(len(strip["signal"]))]
        out.append(
            _line_chart(
                xs,
                strip["signal"],
                "ECG, first 10 s, R-peaks marked",
                strip.get("unit", ""),
                [p / fs for p in strip.get("rPeaks", [])],
            )
        )

    out.append(Paragraph("HRV time domain (first 5 minutes, corrected RR)", h2))
    td = m.get("timeDomain")
    if td:
        out.append(
            _table(
                [
                    ["Mean RR", "Mean HR", "SDNN", "RMSSD", "pNNI20", "pNNI50", "Beats"],
                    [
                        _n(td["meanRr"], 1, "ms"),
                        _n(td["meanHr"], 1, "bpm"),
                        _n(td["sdnn"], 1, "ms"),
                        _n(td["rmssd"], 1, "ms"),
                        _n(td["pnni20"], 1, "%"),
                        _n(td["pnni50"], 1, "%"),
                        _t(td["beats"]),
                    ],
                ]
            )
        )
    else:
        out.append(Paragraph(_t(m.get("unavailable", {}).get("timeDomain", "Unavailable")), body))

    out.append(Paragraph("HRV frequency domain (Lomb-Scargle)", h2))
    fd = m.get("frequencyDomain")
    if fd:
        rows = [["Band", "Range (Hz)", "Peak (Hz)", "Power (ms^2)", "%", "n.u."]]
        for k in ("vlf", "lf", "hf"):
            bd = fd["bands"][k]
            rows.append(
                [
                    k.upper(),
                    f"{bd['rangeHz'][0]}-{bd['rangeHz'][1]}",
                    _n(bd["peakHz"], 3),
                    _n(bd["power"], 1),
                    _n(bd["powerPct"], 1),
                    _n(bd["powerNu"], 1),
                ]
            )
        rows.append(["Total", "", "", _n(fd["totalPower"], 1), "", ""])
        out.append(_table(rows))
        out.append(Paragraph(_t(f"LF/HF ratio: {_n(fd.get('lfHf'), 3)}"), body))
        out.append(_line_chart(fd["freqs"], fd["power"], "Power spectral density", "ms^2/Hz"))
    else:
        out.append(
            Paragraph(_t(m.get("unavailable", {}).get("frequencyDomain", "Unavailable")), body)
        )

    out.append(Paragraph("Poincare and respiration", h2))
    pc, resp = m.get("poincare") or {}, m.get("respiratoryRate") or {}
    out.append(
        _table(
            [
                ["SD1", "SD2", "SD1/SD2", "Respiratory rate", "HF peak", "Movement load"],
                [
                    _n(pc.get("sd1"), 1, "ms"),
                    _n(pc.get("sd2"), 1, "ms"),
                    _n(pc.get("sd1Sd2"), 3),
                    _n(resp.get("value"), 1, "br/min"),
                    _n(resp.get("hfPeakHz"), 3, "Hz"),
                    "n/a (no accelerometer data)",
                ],
            ]
        )
    )

    out.append(Paragraph("Unavailable metrics", h2))
    unavail = m.get("unavailable", {})
    out.append(Paragraph(_t("; ".join(f"{k}: {v}" for k, v in unavail.items()) or "None"), body))

    prov = provenance(session, result, files, generated_at)
    out.append(Paragraph("Method and provenance", h2))
    out.append(
        Paragraph(
            _t(
                "Metrics follow design-spec §6 (Pan-Tompkins-style R-peaks; 11-beat median "
                "artefact rule; 5-minute HRV window; Lomb-Scargle PSD 0.002-0.5 Hz scaled to RR "
                "variance; Edwards TRIMP). These are research estimates, not a validated "
                "clinical result."
            ),
            body,
        )
    )
    out.extend(
        Paragraph(_t(f"Provisional rule {k}: {v}"), body)
        for k, v in prov["provisionalRules"].items()
    )
    out.extend(
        Paragraph(
            _t(
                f"Source file: {f['name']} ({f['format']}, {f['sizeBytes']} bytes, "
                f"SHA-256 {f['sha256'][:16]}...)"
            ),
            body,
        )
        for f in prov["sourceFiles"]
    )
    out.append(
        Paragraph(
            _t(
                f"Analysis version {prov['analysisVersion']} · analysed "
                f"{prov['analysedAt']} · report generated {prov['generatedAt']}"
            ),
            body,
        )
    )

    buf = io.BytesIO()
    SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=6 * mm,
        rightMargin=6 * mm,
        topMargin=6 * mm,
        bottomMargin=6 * mm,
        title="NetriBeat HRV report",
        author="NetriBeat",
    ).build(out)
    return buf.getvalue()
