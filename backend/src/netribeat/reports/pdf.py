"""PDF session report from stored results (ReportLab). No formula is recomputed here."""

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
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from netribeat.sessions.models import Recording

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


def render(rec: Recording, owner_label: str, generated_at: datetime) -> bytes:
    """One or two pages: session details, heart rate, zones, training and movement load."""
    m, sig = rec.metrics or {}, rec.signals or {}
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
    hr, hr_max, inputs = m.get("hr") or {}, m.get("hrMax") or {}, m.get("inputs") or {}
    out: list[Any] = [
        Paragraph("NetriBeat session report", h1),
        Paragraph(
            _t(
                f"{rec.type.title()} session · {owner_label} · recorded "
                f"{rec.recorded_at:%Y-%m-%d %H:%M} UTC"
            ),
            body,
        ),
        Spacer(1, 4),
        _table(
            [
                ["Duration", "Age", "Gender", "Resting HR", "Max HR used", "Steps"],
                [
                    _n((rec.duration_s or 0) / 60, 1, "min"),
                    _t(inputs.get("age") if inputs.get("age") is not None else "n/a"),
                    _t(inputs.get("gender") or "n/a"),
                    _n(inputs.get("restingHr"), 0, "bpm"),
                    _t(
                        f"{hr_max['value']} bpm ({hr_max.get('label', '')})"
                        if hr_max.get("value")
                        else "n/a"
                    ),
                    _t(m.get("steps")),
                ],
            ]
        ),
        Paragraph("Heart rate", h2),
        _table(
            [
                ["Average", "Minimum", "Maximum"],
                [
                    _n(hr.get("avg"), 0, "bpm"),
                    _n(hr.get("min"), 0, "bpm"),
                    _n(hr.get("max"), 0, "bpm"),
                ],
            ]
        ),
        Spacer(1, 4),
        _line_chart(
            (sig.get("hr") or {}).get("tS", []),
            (sig.get("hr") or {}).get("bpm", []),
            "Heart rate (3 s, smoothed) over time (s)",
            "bpm",
        ),
        Paragraph("Heart-rate zones", h2),
    ]
    zones = m.get("timeInZonesS")
    if zones:
        total = sum(zones.values()) or 1
        out.append(
            _table(
                [["Zone", "Time", "Share"]]
                + [
                    [
                        label,
                        f"{int(zones.get(k, 0) // 60)}:{int(zones.get(k, 0) % 60):02d}",
                        f"{zones.get(k, 0) / total * 100:.0f} %",
                    ]
                    for k, label in ZONE_LABELS
                ]
            )
        )
    else:
        out.append(Paragraph(_t(m.get("zonesUnavailableReason") or "Not available"), body))

    out += [
        Paragraph("Training and movement load", h2),
        _table(
            [
                ["Training load", "Training intensity", "Movement load", "Movement intensity"],
                [
                    _n(m.get("trainingLoad"), 1, "AU"),
                    _n(m.get("trainingIntensity"), 3, "AU/min"),
                    _n(m.get("movementLoad"), 3, "RMS-h"),
                    _n(m.get("movementIntensity"), 3),
                ],
            ]
        ),
    ]
    if m.get("trainingLoad") is None and m.get("zonesUnavailableReason"):
        out.append(Paragraph(_t(m["zonesUnavailableReason"]), body))
    out += [
        Spacer(1, 4),
        _line_chart(
            (sig.get("rms") or {}).get("tS", []),
            (sig.get("rms") or {}).get("value", []),
            "Movement (accelerometer RMS, 3 s) over time (s)",
            "RMS",
        ),
        Paragraph("Method", h2),
        Paragraph(
            _t(
                "Decoded from the Synapse sensor hex file (RR, accelerometer RMS and steps). "
                "HR series: 3 s buckets with exponential smoothing; zones as % of max HR; "
                "training load: Banister TRIMP; movement load: RMS-hours (svc-sessions method). "
                "Research estimates, not a validated clinical result."
            ),
            body,
        ),
        Paragraph(
            _t(
                f"Source file: {rec.file_name} (session {rec.part + 1}, {rec.file_size} bytes) · "
                f"analysis version {m.get('analysisVersion')} · report generated "
                f"{generated_at:%Y-%m-%d %H:%M} UTC"
            ),
            body,
        ),
    ]

    buf = io.BytesIO()
    SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=12 * mm,
        rightMargin=12 * mm,
        topMargin=12 * mm,
        bottomMargin=12 * mm,
        title="NetriBeat session report",
        author="NetriBeat",
    ).build(out)
    return buf.getvalue()
