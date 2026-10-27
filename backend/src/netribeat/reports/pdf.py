"""Two-page PDF session report (matplotlib). Only stored results are drawn; nothing is
recomputed here.

Page 1, HRV: subject, RR tachogram, time domain, RR histogram, Poincaré, frequency domain
(Welch FFT and AR) with the spectrum, nonlinear and autonomic components, DFA.
Page 2, Session: heart-rate summary, HR over time in zones, time in zones, training and
movement load, HRV over time, movement and respiration.

Missing values are printed as "—".
"""

from __future__ import annotations

import io
from datetime import datetime
from itertools import pairwise
from typing import Any

import matplotlib

matplotlib.use("Agg")  # no display on the server

import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Ellipse, FancyBboxPatch, Rectangle
from matplotlib.ticker import FuncFormatter

from netribeat.sessions.engine import IST
from netribeat.sessions.models import Recording
from netribeat.sessions.processing import athlete_name

# Brand colours (frontend tokens.css, light theme)
INK = "#141414"
MUTED = "#5c5852"
ORANGE = "#f26b1d"
ORANGE_DARK = "#b4460a"
LINE = "#e8e5df"
SOFT = "#f8f7f4"
ZONES = [  # key, label, colour (below Z1 … Z5)
    ("belowZ1", "Below Z1  < 50 %", "#c9c4bc"),
    ("z1", "Z1  50–60 %", "#7b858f"),
    ("z2", "Z2  60–70 %", "#3b6fb6"),
    ("z3", "Z3  70–80 %", "#2f8a68"),
    ("z4", "Z4  80–90 %", "#a97c00"),
    ("z5", "Z5  ≥ 90 %", "#c83d31"),
]
BANDS = (("vlf", 0.0, 0.04, "#d9d4cc"), ("lf", 0.04, 0.15, "#fbd3b8"), ("hf", 0.15, 0.4, "#f5a26c"))
DASH = "—"
A4 = (8.27, 11.69)

plt.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 7,
        "axes.edgecolor": "#b9b4ad",
        "axes.labelcolor": MUTED,
        "axes.linewidth": 0.6,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "xtick.labelsize": 6,
        "ytick.labelsize": 6,
        "axes.labelsize": 6.5,
        "axes.titlesize": 7.5,
        "pdf.fonttype": 42,
    }
)


# ------------------------------------------------------------------ formatting


def fmt(v: Any, nd: int = 1, unit: str = "") -> str:
    """Number with `nd` decimals (and unit), or a dash when missing."""
    if v is None or v == "":
        return DASH
    if isinstance(v, int | float):
        if v != v:  # NaN
            return DASH
        text = f"{v:,.{nd}f}" if nd else f"{round(v):,}"
    else:
        text = str(v)
    return f"{text} {unit}".strip()


def hms(seconds: float | None) -> str:
    if seconds is None:
        return DASH
    s = round(seconds)
    return (
        f"{s // 3600}:{s % 3600 // 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60}:{s % 60:02d}"
    )


def time_axis(ax: Any) -> None:
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: hms(max(v, 0))))


# ------------------------------------------------------------------ page furniture


def recorded(rec: Recording) -> str:
    """Header subtitle: session type and recording time (no personal names)."""
    return f"{rec.type.title()} session · {rec.recorded_at.astimezone(IST):%d %b %Y, %H:%M} IST"


def logo(fig: Figure, x: float, y: float, h: float) -> None:
    """NetriBeat mark: orange rounded square with a white pulse line, and the word mark."""
    w = h * A4[1] / A4[0]
    fig.add_artist(
        FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle="round,pad=0,rounding_size=0.006",
            transform=fig.transFigure,
            fc=ORANGE,
            ec="none",
        )
    )
    px = [0.12, 0.32, 0.42, 0.52, 0.62, 0.72, 0.88]
    py = [0.5, 0.5, 0.8, 0.2, 0.64, 0.5, 0.5]
    fig.add_artist(
        Line2D(
            [x + w * a for a in px],
            [y + h * b for b in py],
            transform=fig.transFigure,
            color="white",
            lw=1.4,
            solid_joinstyle="round",
            solid_capstyle="round",
        )
    )
    fig.text(
        x + w + 0.009, y + h / 2, "Netri", color="white", fontsize=15, weight="bold", va="center"
    )
    fig.text(
        x + w + 0.074, y + h / 2, "Beat", color=ORANGE, fontsize=15, weight="bold", va="center"
    )


def header(fig: Figure, title: str, subtitle: str, page: int) -> None:
    fig.add_artist(Rectangle((0, 0.948), 1, 0.052, transform=fig.transFigure, fc=INK, ec="none"))
    fig.add_artist(Rectangle((0, 0.945), 1, 0.003, transform=fig.transFigure, fc=ORANGE, ec="none"))
    logo(fig, 0.04, 0.959, 0.03)
    fig.text(
        0.96, 0.981, title, color="white", fontsize=11.5, weight="bold", ha="right", va="center"
    )
    fig.text(
        0.96,
        0.961,
        f"{subtitle}  ·  page {page} / 2",
        color="#a9a6a1",
        fontsize=7,
        ha="right",
        va="center",
    )


def footer(fig: Figure, rec: Recording, generated_at: datetime) -> None:
    fig.add_artist(
        Line2D([0.04, 0.96], [0.03, 0.03], transform=fig.transFigure, color=LINE, lw=0.8)
    )
    fig.text(
        0.04,
        0.018,
        f"{rec.file_name} · session {rec.part + 1} · id {str(rec.id)[:8]}",
        color=MUTED,
        fontsize=6,
    )
    fig.text(
        0.96,
        0.018,
        f"Generated {generated_at.astimezone(IST):%d %b %Y %H:%M} IST · research "
        "estimates, not a clinical diagnosis",
        color=MUTED,
        fontsize=6,
        ha="right",
    )


def section(fig: Figure, x: float, y: float, text: str) -> None:
    fig.add_artist(
        Rectangle((x, y - 0.001), 0.004, 0.012, transform=fig.transFigure, fc=ORANGE, ec="none")
    )
    fig.text(x + 0.009, y, text, color=INK, fontsize=9, weight="bold", va="bottom")


def table(
    fig: Figure,
    x: float,
    y: float,
    widths: list[float],
    rows: list[list[str]],
    row_h: float = 0.0152,
) -> float:
    """Striped table at figure coordinates (first row is the header); returns the y below."""
    total = sum(widths)
    for i, row in enumerate(rows):
        top = y - i * row_h
        if i == 0:
            fig.add_artist(
                Line2D(
                    [x, x + total],
                    [top - row_h + 0.002] * 2,
                    transform=fig.transFigure,
                    color=ORANGE,
                    lw=0.8,
                )
            )
        elif i % 2 == 0:
            fig.add_artist(
                Rectangle(
                    (x, top - row_h + 0.002),
                    total,
                    row_h,
                    transform=fig.transFigure,
                    fc=SOFT,
                    ec="none",
                )
            )
        cx = x
        for j, cell in enumerate(row):
            fig.text(
                cx + (0.004 if j == 0 else widths[j] - 0.004),
                top - row_h / 2 + 0.002,
                cell,
                fontsize=6.6,
                va="center",
                ha="left" if j == 0 else "right",
                color=MUTED if i == 0 else INK,
                weight="bold" if i == 0 or j == 0 else "normal",
            )
            cx += widths[j]
    return y - len(rows) * row_h


def tile(
    fig: Figure,
    x: float,
    y: float,
    w: float,
    h: float,
    label: str,
    value: str,
    sub: str = "",
    accent: bool = False,
) -> None:
    fig.add_artist(
        FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle="round,pad=0,rounding_size=0.008",
            transform=fig.transFigure,
            fc=SOFT,
            ec=LINE,
            lw=0.7,
        )
    )
    if accent:
        fig.add_artist(
            Rectangle(
                (x, y + 0.008), 0.0035, h - 0.016, transform=fig.transFigure, fc=ORANGE, ec="none"
            )
        )
    fig.text(x + 0.012, y + h - 0.015, label.upper(), fontsize=5.8, color=MUTED, weight="bold")
    fig.text(x + 0.012, y + h * 0.42, value, fontsize=12, color=INK, weight="bold", va="center")
    if sub:
        fig.text(x + 0.012, y + 0.008, sub[:44], fontsize=5.6, color=MUTED)


def axes(fig: Figure, rect: tuple[float, float, float, float], title: str = "") -> Any:
    ax = fig.add_axes(rect)
    ax.set_facecolor("white")
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.grid(True, color=LINE, lw=0.5)
    ax.set_axisbelow(True)
    if title:
        ax.set_title(title, loc="left", color=INK, weight="bold", pad=4)
    return ax


def no_data(ax: Any, text: str) -> None:
    ax.text(
        0.5,
        0.5,
        text,
        transform=ax.transAxes,
        ha="center",
        va="center",
        color=MUTED,
        fontsize=7,
        wrap=True,
    )
    ax.set_xticks([])
    ax.set_yticks([])


# ------------------------------------------------------------------ page 1: HRV


def subject_box(fig: Figure, rec: Recording, m: dict[str, Any]) -> None:
    sub = m.get("subject") or {}
    h, w = sub.get("heightCm"), sub.get("weightKg")
    bmi = w / (h / 100) ** 2 if h and w else None
    sample = (m.get("advanced") or {}).get("sample") or {}
    start = sample.get("startS")
    cells = [
        ("Athlete", athlete_name(rec.athlete_name, rec.file_name) or DASH),
        ("Age", fmt(sub.get("age"), 0, "y")),
        ("Gender", (sub.get("gender") or DASH).title()),
        ("Height", fmt(h, 0, "cm")),
        ("Weight", fmt(w, 1, "kg")),
        ("BMI", fmt(bmi, 1)),
        ("Resting HR", fmt(sub.get("restingHr"), 0, "bpm")),
        ("Max HR used", fmt(sub.get("maxHr"), 0, "bpm")),
        ("Session", rec.type.title()),
        ("Recorded (IST)", f"{rec.recorded_at.astimezone(IST):%d %b %Y %H:%M}"),
        ("Duration", hms(rec.duration_s)),
        (
            "HRV sample",
            f"{hms(start)} – {hms((start or 0) + (sample.get('lengthS') or 0))}"
            if start is not None
            else DASH,
        ),
    ]
    x0, y0, bw, bh = 0.04, 0.868, 0.92, 0.066
    fig.add_artist(
        FancyBboxPatch(
            (x0, y0),
            bw,
            bh,
            boxstyle="round,pad=0,rounding_size=0.01",
            transform=fig.transFigure,
            fc=SOFT,
            ec=LINE,
            lw=0.7,
        )
    )
    cw = bw / 6
    for i, (k, v) in enumerate(cells):
        cx, cy = x0 + 0.012 + (i % 6) * cw, y0 + bh - 0.016 - (i // 6) * 0.031
        fig.text(cx, cy, k.upper(), fontsize=5.6, color=MUTED, weight="bold")
        fig.text(cx, cy - 0.0125, v[:26], fontsize=7.6, color=INK, weight="bold")


def page_hrv(pdf: PdfPages, rec: Recording, at: datetime) -> None:
    m, s = rec.metrics or {}, rec.signals or {}
    adv, advs = m.get("advanced") or {}, s.get("advanced") or {}
    nl = adv.get("nonlinear") or {}
    unavailable = (adv.get("unavailable") or {}).get("all") or DASH
    fig = plt.figure(figsize=A4)
    header(fig, "HRV Analysis Report", recorded(rec), 1)
    subject_box(fig, rec, m)

    # RR tachogram
    section(fig, 0.04, 0.84, "RR intervals")
    ax = axes(fig, (0.08, 0.715, 0.88, 0.115))
    tach = advs.get("tachogram") or {}
    if tach.get("tS"):
        t, rr = tach["tS"], tach["rrMs"]
        ax.plot(t, rr, color=INK, lw=0.5)
        sample = adv.get("sample") or {}
        if sample:
            s0 = (t[0] - rr[0] / 1000) + (sample.get("startS") or 0)
            ax.axvspan(s0, s0 + (sample.get("lengthS") or 0), color=ORANGE, alpha=0.13, lw=0)
        flags = tach.get("flags") or []
        if flags:
            ax.scatter(
                [t[i] for i in flags], [rr[i] for i in flags], s=6, color=ORANGE_DARK, zorder=3
            )
        ax.set_ylabel("RR (ms)")
        time_axis(ax)
        ax.text(
            1.0,
            1.05,
            f"shaded: analysed sample · {fmt(sample.get('beats'), 0)} beats · "
            f"{fmt(sample.get('beatsCorrectedPct'), 2)} % corrected (orange dots)",
            transform=ax.transAxes,
            ha="right",
            fontsize=6,
            color=MUTED,
        )
    else:
        no_data(ax, unavailable)

    # Time domain | histogram | Poincaré
    td = adv.get("timeDomain") or {}
    section(fig, 0.04, 0.66, "Time domain")
    table(
        fig,
        0.04,
        0.652,
        [0.17, 0.10],
        [
            ["Variable", "Value"],
            ["Mean RR", fmt(td.get("meanRr"), 0, "ms")],
            ["SDNN", fmt(td.get("sdnn"), 1, "ms")],
            ["Mean HR", fmt(td.get("meanHr"), 0, "bpm")],
            ["SD HR", fmt(td.get("sdHr"), 1, "bpm")],
            ["Min / max HR", f"{fmt(td.get('minHr'), 0)} / {fmt(td.get('maxHr'), 0)} bpm"],
            ["RMSSD", fmt(td.get("rmssd"), 1, "ms")],
            ["NN50", fmt(td.get("nn50"), 0, "beats")],
            ["pNN50", fmt(td.get("pnn50"), 1, "%")],
            ["RR triangular index", fmt(td.get("triangularIndex"), 2)],
            ["TINN", fmt(td.get("tinn"), 0, "ms")],
            ["Stress index", fmt(td.get("stressIndex"), 1)],
        ],
    )

    ax = axes(fig, (0.385, 0.47, 0.26, 0.165), "RR histogram")
    hist = advs.get("histogram") or {}
    if hist.get("counts"):
        e, c = hist["edgesMs"], hist["counts"]
        ax.bar(
            e[:-1],
            c,
            width=[b - a for a, b in pairwise(e)],
            align="edge",
            color=ORANGE,
            edgecolor="none",
        )
        ax.set_xlabel("RR (ms)")
        ax.set_ylabel("beats")
    else:
        no_data(ax, DASH)

    ax = axes(fig, (0.715, 0.47, 0.245, 0.165), "Poincaré plot")
    rr_s = (advs.get("sample") or {}).get("rrMs") or []
    if len(rr_s) > 2:
        ax.scatter(rr_s[:-1], rr_s[1:], s=3, color=INK, alpha=0.5, lw=0)
        mean = sum(rr_s) / len(rr_s)
        sd1, sd2 = nl.get("sd1"), nl.get("sd2")
        if sd1 and sd2:
            ax.add_patch(
                Ellipse((mean, mean), 4 * sd2, 4 * sd1, angle=45, fill=False, ec=ORANGE, lw=1.3)
            )
        lo, hi = min(rr_s), max(rr_s)
        ax.plot([lo, hi], [lo, hi], color="#c9c4bc", lw=0.6, ls="--")
        ax.set_xlabel("RR n (ms)")
        ax.set_ylabel("RR n+1 (ms)")
        ax.set_aspect("equal", adjustable="datalim")
    else:
        no_data(ax, DASH)

    # Frequency domain
    fd = adv.get("frequencyDomain") or {}
    fft, ar = fd.get("fft") or {}, fd.get("ar") or {}
    section(fig, 0.04, 0.415, "Frequency domain")

    def band_row(name: str) -> list[str]:
        fb = (fft.get("bands") or {}).get(name, {})
        ab = (ar.get("bands") or {}).get(name, {})
        return [
            name.upper(),
            fmt(fb.get("peakHz"), 3),
            fmt(fb.get("power"), 0),
            fmt(fb.get("powerPct"), 1),
            fmt(fb.get("powerNu"), 1),
            fmt(ab.get("peakHz"), 3),
            fmt(ab.get("power"), 0),
            fmt(ab.get("powerPct"), 1),
            fmt(ab.get("powerNu"), 1),
        ]

    widths = [0.045, 0.054, 0.055, 0.04, 0.046, 0.058, 0.055, 0.04, 0.046]
    fig.text(
        0.04 + 0.045 + 0.0975,
        0.398,
        "Welch FFT",
        ha="center",
        fontsize=6.4,
        color=ORANGE_DARK,
        weight="bold",
    )
    fig.text(
        0.04 + 0.045 + 0.195 + 0.0995,
        0.398,
        "Autoregressive (AR)",
        ha="center",
        fontsize=6.4,
        color=ORANGE_DARK,
        weight="bold",
    )
    table(
        fig,
        0.04,
        0.395,
        widths,
        [
            ["Band", "Peak Hz", "ms²", "%", "n.u.", "Peak Hz", "ms²", "%", "n.u."],
            band_row("vlf"),
            band_row("lf"),
            band_row("hf"),
            [
                "Total",
                "",
                fmt(fft.get("totalPower"), 0),
                "",
                "",
                "",
                fmt(ar.get("totalPower"), 0),
                "",
                "",
            ],
            ["LF/HF", "", fmt(fft.get("lfHf"), 3), "", "", "", fmt(ar.get("lfHf"), 3), "", ""],
        ],
    )

    ax = axes(fig, (0.575, 0.27, 0.385, 0.135), "Power spectrum (Welch FFT)")
    spec = (advs.get("spectrum") or {}).get("fft") or {}
    if spec.get("freqs"):
        f, p = spec["freqs"], spec["power"]
        for name, lo, hi, colour in BANDS:
            sel = [(x, y) for x, y in zip(f, p, strict=False) if lo <= x <= hi]
            if sel:
                ax.fill_between(
                    [a for a, _ in sel], [b for _, b in sel], color=colour, lw=0, label=name.upper()
                )
        ax.plot(f, p, color=INK, lw=0.8)
        ax.set_xlim(0, 0.5)
        ax.set_xlabel("Frequency (Hz)")
        ax.set_ylabel("ms²/Hz")
        ax.legend(loc="upper right", fontsize=5.8, frameon=False, ncol=3)
    else:
        no_data(ax, DASH)

    # Nonlinear | autonomic | DFA
    ans = adv.get("ans") or {}
    pns, sns = ans.get("pns") or {}, ans.get("sns") or {}
    rq = nl.get("recurrence") or {}
    section(fig, 0.04, 0.215, "Nonlinear")
    table(
        fig,
        0.04,
        0.207,
        [0.17, 0.10],
        [
            ["Variable", "Value"],
            ["Poincaré SD1 / SD2", f"{fmt(nl.get('sd1'), 1)} / {fmt(nl.get('sd2'), 1)} ms"],
            ["SD2 / SD1", fmt(nl.get("sd2Sd1"), 2)],
            ["Approximate entropy", fmt(nl.get("apen"), 3)],
            ["Sample entropy", fmt(nl.get("sampen"), 3)],
            ["DFA α1 / α2", f"{fmt(nl.get('dfaAlpha1'), 2)} / {fmt(nl.get('dfaAlpha2'), 2)}"],
            ["Recurrence REC / DET", f"{fmt(rq.get('rec'), 1)} / {fmt(rq.get('det'), 1)} %"],
        ],
    )
    section(fig, 0.36, 0.215, "Autonomic balance")
    table(
        fig,
        0.36,
        0.207,
        [0.15, 0.08],
        [
            ["Parasympathetic", ""],
            ["Mean RR", fmt(pns.get("meanRr"), 0, "ms")],
            ["RMSSD", fmt(pns.get("rmssd"), 1, "ms")],
            ["SD1 share", fmt(pns.get("sd1Pct"), 1, "%")],
        ],
    )
    table(
        fig,
        0.36,
        0.137,
        [0.15, 0.08],
        [
            ["Sympathetic", ""],
            ["Mean HR", fmt(sns.get("meanHr"), 0, "bpm")],
            ["Stress index", fmt(sns.get("stressIndex"), 1)],
            ["SD2 share", fmt(sns.get("sd2Pct"), 1, "%")],
        ],
    )

    ax = axes(fig, (0.67, 0.08, 0.29, 0.125), "DFA  log F(n) vs log n")
    dfa = advs.get("dfa") or {}
    if dfa.get("short") or dfa.get("long"):
        for key, colour, lab in (("short", ORANGE, "α1 (4–16)"), ("long", INK, "α2 (16–64)")):
            pts = dfa.get(key) or []
            if pts:
                ax.plot(
                    [a for a, _ in pts],
                    [b for _, b in pts],
                    "o-",
                    ms=2,
                    lw=0.8,
                    color=colour,
                    label=lab,
                )
        ax.legend(fontsize=5.8, frameon=False)
        ax.set_xlabel("log10 n (beats)")
    else:
        no_data(ax, DASH)

    opts = adv.get("options") or {}
    fig.text(
        0.04,
        0.042,
        f"Artefact correction: {opts.get('correction', DASH)} · detrending: "
        f"{opts.get('detrend', DASH)} · FFT window {fmt(opts.get('welch_window_s'), 0, 's')}"
        f" · AR order {fmt(opts.get('ar_order'), 0)} · HRV with Kubios-compatible "
        "definitions",
        fontsize=6,
        color=MUTED,
    )
    footer(fig, rec, at)
    pdf.savefig(fig)  # type: ignore[no-untyped-call]
    plt.close(fig)


# ------------------------------------------------------------------ page 2: session


def page_session(pdf: PdfPages, rec: Recording, at: datetime) -> None:
    m, s = rec.metrics or {}, rec.signals or {}
    hr = m.get("hr") or {}
    hr_max = (m.get("hrMax") or {}).get("value")
    fig = plt.figure(figsize=A4)
    header(fig, "Session & Training Report", recorded(rec), 2)

    def pct(v: float | None) -> str:
        return f"{round(100 * v / hr_max)} % of max HR" if v and hr_max else ""

    resp = m.get("respiratoryRate") or {}
    tiles = [
        ("Average HR", fmt(hr.get("avg"), 0, "bpm"), pct(hr.get("avg")), True),
        ("Maximum HR", fmt(hr.get("max"), 0, "bpm"), pct(hr.get("max")), False),
        ("Minimum HR", fmt(hr.get("min"), 0, "bpm"), pct(hr.get("min")), False),
        ("Max HR used", fmt(hr_max, 0, "bpm"), (m.get("hrMax") or {}).get("label", ""), False),
        ("Training load", fmt(m.get("trainingLoad"), 1, "AU"), "Banister TRIMP", True),
        ("Training intensity", fmt(m.get("trainingIntensity"), 2), "load per minute", False),
        (
            "Movement load",
            fmt(m.get("movementLoad"), 2, "RMS·h"),
            f"intensity {fmt(m.get('movementIntensity'), 2)}",
            False,
        ),
        (
            "Steps · respiration",
            f"{fmt(m.get('steps'), 0)} · {fmt(resp.get('value'), 1)}",
            "steps · breaths per min",
            False,
        ),
    ]
    for i, (label, value, sub, accent) in enumerate(tiles):
        tile(
            fig,
            0.04 + (i % 4) * 0.232,
            0.862 - (i // 4) * 0.072,
            0.22,
            0.064,
            label,
            value,
            sub,
            accent,
        )
    if m.get("zonesUnavailableReason"):
        fig.text(
            0.04, 0.778, f"Note: {m['zonesUnavailableReason']}", fontsize=6.4, color=ORANGE_DARK
        )

    section(fig, 0.04, 0.755, "Heart rate over time")
    ax = axes(fig, (0.08, 0.565, 0.88, 0.175))
    hs = s.get("hr") or {}
    if hs.get("tS"):
        if hr_max:
            edges = [0, 0.5, 0.6, 0.7, 0.8, 0.9, 1.3]
            for (_, _, colour), lo, hi in zip(ZONES, edges[:-1], edges[1:], strict=False):
                ax.axhspan(lo * hr_max, hi * hr_max, color=colour, alpha=0.10, lw=0)
        ax.plot(hs["tS"], hs["bpm"], color=ORANGE_DARK, lw=0.9)
        lo, hi = min(hs["bpm"]), max(hs["bpm"])
        ax.set_ylim(max(lo - 10, 30), hi + 10)
        ax.set_ylabel("bpm")
        time_axis(ax)
        if hr_max:
            ax.text(
                1.0,
                1.03,
                "background: heart-rate zones",
                transform=ax.transAxes,
                ha="right",
                fontsize=6,
                color=MUTED,
            )
    else:
        no_data(ax, DASH)

    section(fig, 0.04, 0.515, "Time in heart-rate zones")
    ax = axes(fig, (0.13, 0.33, 0.32, 0.17))
    zones = m.get("timeInZonesS")
    if zones:
        total = sum(zones.values()) or 1
        names = [z[1] for z in ZONES][::-1]
        vals = [zones.get(z[0], 0) for z in ZONES][::-1]
        ax.barh(names, vals, color=[z[2] for z in ZONES][::-1], height=0.62)
        for i, v in enumerate(vals):
            ax.text(
                v, i, f"  {hms(v)}  ({100 * v / total:.0f} %)", va="center", fontsize=6, color=INK
            )
        ax.set_xlim(0, (max(vals) or 1) * 1.5)
        ax.grid(False)
        ax.set_xticks([])
        ax.spines["bottom"].set_visible(False)
    else:
        no_data(ax, m.get("zonesUnavailableReason") or DASH)

    section(fig, 0.53, 0.515, "HRV over time (60 s windows)")
    ax = axes(fig, (0.58, 0.33, 0.32, 0.17))
    tv = (s.get("advanced") or {}).get("timeVarying") or {}
    if tv.get("tS"):
        ax.plot(tv["tS"], tv["rmssd"], color=ORANGE, lw=1.0)
        ax.set_ylabel("RMSSD (ms)", color=ORANGE_DARK)
        time_axis(ax)
        ax2 = ax.twinx()
        ax2.plot(tv["tS"], tv["meanHr"], color=INK, lw=0.8)
        ax2.set_ylabel("Mean HR (bpm)")
        ax2.spines["top"].set_visible(False)
        ax2.tick_params(labelsize=6)
    else:
        no_data(ax, DASH)

    section(fig, 0.04, 0.28, "Movement (accelerometer RMS, 3 s)")
    ax = axes(fig, (0.08, 0.1, 0.4, 0.165))
    rms = s.get("rms") or {}
    if rms.get("tS"):
        ax.fill_between(rms["tS"], rms["value"], color=ORANGE, alpha=0.25, lw=0)
        ax.plot(rms["tS"], rms["value"], color=ORANGE_DARK, lw=0.6)
        ax.set_ylabel("RMS")
        time_axis(ax)
    else:
        no_data(ax, DASH)

    section(fig, 0.53, 0.28, "Respiratory rate per minute")
    ax = axes(fig, (0.58, 0.1, 0.38, 0.165))
    per_min = (s.get("perMinute") or {}).get("respiratoryRate") or []
    pts = [(i + 1, v) for i, v in enumerate(per_min) if v is not None]
    if pts:
        ax.plot(
            [a for a, _ in pts],
            [b for _, b in pts],
            "o-",
            color=INK,
            ms=2.5,
            lw=0.8,
            mfc=ORANGE,
            mec=ORANGE,
        )
        ax.set_xlabel("minute")
        ax.set_ylabel("breaths per min")
    else:
        no_data(ax, DASH)

    fig.text(
        0.04,
        0.042,
        "Method: Synapse hex → RR, accelerometer RMS and steps · HR in 3 s buckets, exponentially "
        "smoothed · zones as % of max HR · training load Banister TRIMP · movement load RMS-hours",
        fontsize=6,
        color=MUTED,
    )
    footer(fig, rec, at)
    pdf.savefig(fig)  # type: ignore[no-untyped-call]
    plt.close(fig)


def render(rec: Recording, generated_at: datetime) -> bytes:
    buf = io.BytesIO()
    meta = {"Title": "NetriBeat session report", "Author": "NetriBeat"}
    with PdfPages(buf, metadata=meta) as pdf:
        page_hrv(pdf, rec, generated_at)
        page_session(pdf, rec, generated_at)
    return buf.getvalue()
