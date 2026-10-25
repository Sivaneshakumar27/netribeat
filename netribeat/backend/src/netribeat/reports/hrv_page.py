"""One-page HRV results sheet in the layout of a Kubios HRV report (header, RR data,
analysed sample, ANS, time / frequency / nonlinear results with plots).

Rendered with matplotlib (Agg) to a PNG that pdf.py places as page 1. Reads stored
results only (metrics["advanced"], signals["advanced"]); nothing is recomputed here.
"""

from __future__ import annotations

import io
from datetime import datetime
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Ellipse, Rectangle
from matplotlib.ticker import FuncFormatter

BLUE, ORANGE, GREY, RED, INK, MUTED = (
    "#2b7bba",
    "#e8963c",
    "#8a8a8a",
    "#d23c2a",
    "#111111",
    "#666666",
)
CORRECTION_LABEL = {
    "none": "none",
    "spec": "NetriBeat rule (20 % local median)",
    "very_low": "very low",
    "low": "low",
    "medium": "medium",
    "strong": "strong",
    "very_strong": "very strong",
}


def hms(seconds: float | None) -> str:
    if seconds is None:
        return "-"
    s = round(seconds)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def _f(v: Any, nd: int = 1) -> str:
    if v is None:
        return "-"
    if isinstance(v, int) and not isinstance(v, bool):
        return str(v)
    try:
        return f"{float(v):.{nd}f}"
    except (TypeError, ValueError):
        return str(v)


def _table(
    fig: Any,
    x: float,
    y: float,
    rows: list[list[str]],
    widths: list[float],
    head: bool = True,
    size: float = 7.6,
    step: float = 0.0125,
    aligns: list[str] | None = None,
) -> float:
    aligns = aligns or ["left"] + ["right"] * (len(widths) - 1)
    for i, row in enumerate(rows):
        cx = x
        for j, cell in enumerate(row):
            ha = aligns[j]
            tx = cx + (widths[j] if ha == "right" else 0)
            fig.text(
                tx,
                y - i * step,
                cell,
                fontsize=size,
                ha=ha,
                va="top",
                weight="bold" if (head and i == 0) or cell.endswith(":") else "normal",
                color=INK,
            )
            cx += widths[j]
        if head and i == 0:
            fig.add_artist(Line2D([x, x + sum(widths)], [y - step * 0.85] * 2, lw=0.6, color=INK))
    bottom = y - len(rows) * step
    fig.add_artist(Line2D([x, x + sum(widths)], [bottom + step * 0.2] * 2, lw=0.6, color=INK))
    return bottom


def _style(ax: Any, size: float = 6.5) -> None:
    ax.tick_params(labelsize=size, colors=MUTED, length=2)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color("#bbbbbb")


def render_png(
    *,
    title_sample: str,
    subject: dict[str, Any],
    recorded_at: datetime,
    file_name: str,
    adv: dict[str, Any],
    series: dict[str, Any],
    generated_at: datetime,
    dpi: int = 170,
) -> bytes:
    fig = plt.figure(figsize=(8.27, 11.69), dpi=dpi)
    fig.patch.set_facecolor("white")
    fig.text(0.05, 0.968, f"HRV Results ({title_sample})", fontsize=17, weight="bold", va="top")
    fig.add_artist(Line2D([0.05, 0.95], [0.943, 0.943], lw=1.0, color=GREY))

    # ---- info box
    fig.add_artist(
        Rectangle((0.05, 0.868), 0.30, 0.067, transform=fig.transFigure, color="#eeeeee", lw=0)
    )
    fig.add_artist(
        Rectangle(
            (0.05, 0.868), 0.90, 0.067, transform=fig.transFigure, fill=False, ec="#cccccc", lw=0.6
        )
    )
    sex = (subject.get("sex") or "").capitalize()
    age = subject.get("age")
    line1 = (
        " / ".join(p for p in (sex, f"{age} years" if age else "") if p)
        or "Subject details not set"
    )
    h, w = subject.get("height_cm"), subject.get("weight_kg")
    line2 = (
        f"{h} cm / {w:.1f} kg (BMI={w / (h / 100) ** 2:.1f} kg/m²)"
        if h and w
        else f"{h} cm"
        if h
        else f"{w:.1f} kg"
        if w
        else ""
    )
    left = [
        line1,
        line2,
        f"HR max: {subject['hr_max']} bpm" if subject.get("hr_max") else "HR max: -",
        f"HR rest: {subject['hr_rest']} bpm" if subject.get("hr_rest") else "HR rest: -",
    ]
    for i, t in enumerate(left):
        fig.text(0.06, 0.925 - i * 0.0135, t, fontsize=7.8, va="top")
    sample = adv.get("sample", {})
    opts = adv.get("options", {})
    fig.text(
        0.37, 0.93, f"{recorded_at:%a, %b %d %Y, %H:%M:%S}", fontsize=8.6, weight="bold", va="top"
    )
    mid = [
        f"Measurement length: {hms(sample.get('measurementLengthS'))}",
        "Number of samples: 1",
        f"Beat correction: {CORRECTION_LABEL.get(opts.get('correction', ''), '-')}",
        "Trend removal: "
        + ("Smoothn priors" if opts.get("detrend") == "smoothness_priors" else "none"),
    ]
    for i, t in enumerate(mid):
        fig.text(0.37, 0.913 - i * 0.0118, t, fontsize=7.6, va="top")
    fig.text(0.94, 0.93, file_name[:46], fontsize=6.8, color=MUTED, ha="right", va="top")
    fig.text(0.68, 0.913, f"Sample ({title_sample})", fontsize=7.8, weight="bold", va="top")
    right = [
        f"Start time: {hms(sample.get('startS'))}",
        f"Sample length: {hms(sample.get('lengthS'))}",
        f"Beats corrected: {sample.get('beatsCorrected', '-')} "
        f"({_f(sample.get('beatsCorrectedPct'), 2)} %)",
    ]
    for i, t in enumerate(right):
        fig.text(0.68, 0.900 - i * 0.0118, t, fontsize=7.6, va="top")

    unavailable = adv.get("unavailable", {})
    if "all" in unavailable or "timeDomain" not in adv:
        fig.text(0.5, 0.6, "HRV analysis unavailable", ha="center", fontsize=14, weight="bold")
        fig.text(
            0.5,
            0.57,
            unavailable.get("all", "No RR data"),
            ha="center",
            fontsize=9,
            color=MUTED,
            wrap=True,
        )
        return _png(fig, dpi)

    tach, smp = series["tachogram"], series["sample"]
    # ---- RR data
    ax = fig.add_axes((0.08, 0.768, 0.87, 0.080))
    ts = [t for t in tach["tS"]]
    ax.plot(ts, [v / 1000 for v in tach["rrMs"]], color=BLUE, lw=0.6)
    if smp["tS"]:
        ax.axvspan(smp["tS"][0], smp["tS"][-1], color="#dbe9f5", zorder=0)
        ax.plot(smp["tS"], [v / 1000 for v in smp["trendMs"]], color=RED, lw=0.8)
    flags = set(tach.get("flags", []))
    if flags:
        ax.plot(
            [ts[i] for i in flags],
            [tach["rrMs"][i] / 1000 for i in flags],
            "o",
            ms=2.2,
            mfc="none",
            mec=RED,
            mew=0.6,
        )
    ax.set_xlim(0, max(ts) if ts else 1)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: hms(v)))
    ax.set_title("RR data          RR (s)", fontsize=7.8, loc="left", weight="bold", pad=2)
    _style(ax)

    ax = fig.add_axes((0.08, 0.672, 0.87, 0.075))
    ax.plot(smp["tS"], [v / 1000 for v in smp["detrendedMs"]], color=BLUE, lw=0.6)
    ax.axhline(0, color="#cccccc", lw=0.4)
    ax.set_xlim(smp["tS"][0], smp["tS"][-1])
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: hms(v)))
    ax.set_title(
        "Analyzed Sample (detrended)          RR (s)",
        fontsize=7.8,
        loc="left",
        weight="bold",
        pad=2,
    )
    ax.set_xlabel("Time (h:min:s)", fontsize=7, color=MUTED, labelpad=1)
    _style(ax)

    # ---- ANS
    fig.add_artist(Line2D([0.05, 0.95], [0.632, 0.632], lw=0.5, color="#dddddd"))
    fig.text(0.05, 0.627, "Autonomic nervous system (ANS)", fontsize=8.4, weight="bold", va="top")
    ans = adv["ans"]
    fig.add_artist(
        Rectangle((0.05, 0.527), 0.33, 0.088, transform=fig.transFigure, color="#eeeeee", lw=0)
    )
    fig.text(
        0.215,
        0.611,
        "Parasympathetic nervous system (PNS)",
        fontsize=7.6,
        weight="bold",
        ha="center",
        va="top",
    )
    for j, (lab, val) in enumerate(
        (
            ("Mean RR", f"{_f(ans['pns']['meanRr'], 0)} ms"),
            ("RMSSD", f"{_f(ans['pns']['rmssd'], 1)} ms"),
            ("SD1", f"{_f(ans['pns']['sd1Pct'], 1)} %"),
        )
    ):
        fig.text(0.09 + j * 0.105, 0.598, lab, fontsize=7.4, ha="center", va="top")
        fig.text(0.09 + j * 0.105, 0.586, val, fontsize=8, weight="bold", ha="center", va="top")
    fig.text(
        0.215,
        0.569,
        "Sympathetic nervous system (SNS)",
        fontsize=7.6,
        weight="bold",
        ha="center",
        va="top",
    )
    for j, (lab, val) in enumerate(
        (
            ("Mean HR", f"{_f(ans['sns']['meanHr'], 0)} bpm"),
            ("Stress index", _f(ans["sns"]["stressIndex"], 1)),
            ("SD2", f"{_f(ans['sns']['sd2Pct'], 1)} %"),
        )
    ):
        fig.text(0.09 + j * 0.105, 0.556, lab, fontsize=7.4, ha="center", va="top")
        fig.text(0.09 + j * 0.105, 0.544, val, fontsize=8, weight="bold", ha="center", va="top")
    for x0, color, title in (
        (0.40, "#dceaf6", "PNS activity (recovery)"),
        (0.68, "#fbe3cc", "SNS activity (stress)"),
    ):
        fig.add_artist(
            Rectangle((x0, 0.527), 0.27, 0.088, transform=fig.transFigure, color=color, lw=0)
        )
        fig.text(x0 + 0.135, 0.606, title, fontsize=7.8, weight="bold", ha="center", va="top")
        fig.text(x0 + 0.135, 0.590, "index: not available", fontsize=7.4, ha="center", va="top")
        fig.text(
            x0 + 0.135,
            0.573,
            "Needs Kubios' normative population\nvalues (not provided).\n"
            "Component values are shown on the left.",
            fontsize=6.2,
            color=MUTED,
            ha="center",
            va="top",
            linespacing=1.3,
        )

    # ---- time domain
    td = adv["timeDomain"]
    fig.text(0.05, 0.515, "Time-domain results", fontsize=8.4, weight="bold", va="top")
    rows = [
        ["Variable", "Units", "Value"],
        ["Mean RR*", "(ms)", _f(td["meanRr"], 0)],
        ["Mean HR*", "(bpm)", _f(td["meanHr"], 0)],
        ["Min HR*", "(bpm)", _f(td["minHr"], 0)],
        ["Max HR*", "(bpm)", _f(td["maxHr"], 0)],
        ["SDNN", "(ms)", _f(td["sdnn"], 1)],
        ["RMSSD", "(ms)", _f(td["rmssd"], 1)],
        ["NN50", "(beats)", _f(td["nn50"])],
        ["pNN50", "(%)", _f(td["pnn50"], 2)],
        ["HRV triang.ind.", "", _f(td["triangularIndex"], 2)],
        ["TINN", "(ms)", _f(td["tinn"], 1)],
        ["Stress index", "", _f(td["stressIndex"], 1)],
    ]
    _table(fig, 0.05, 0.500, rows, [0.09, 0.05, 0.05])
    hist = series["histogram"]
    ax = fig.add_axes((0.29, 0.36, 0.105, 0.13))
    edges = hist["edgesMs"]
    ax.bar(
        [e / 1000 for e in edges[:-1]],
        hist["counts"],
        width=(edges[1] - edges[0]) / 1000,
        align="edge",
        color=BLUE,
        lw=0,
    )
    ax.set_title("RR Distribution", fontsize=7.4, pad=2)
    ax.set_xlabel("RR (s)", fontsize=6.5, color=MUTED, labelpad=1)
    ax.set_ylabel("Nbr of beats", fontsize=6.5, color=MUTED, labelpad=1)
    _style(ax, 6)

    # ---- frequency domain (FFT)
    fft = adv["frequencyDomain"]["fft"]
    b = fft["bands"]
    fig.text(0.42, 0.515, "Frequency-domain results", fontsize=8.4, weight="bold", va="top")
    rows = [
        ["Variable", "Units", "VLF", "LF", "HF"],
        ["Frequency band", "(Hz)", "0.00-0.04", "0.04-0.15", "0.15-0.40"],
        ["Peak frequency", "(Hz)", *(_f(b[k]["peakHz"], 3) for k in ("vlf", "lf", "hf"))],
        ["Power", "(ms²)", *(_f(b[k]["power"], 0) for k in ("vlf", "lf", "hf"))],
        ["Power", "(log)", *(_f(b[k]["logPower"], 3) for k in ("vlf", "lf", "hf"))],
        ["Power", "(%)", *(_f(b[k]["powerPct"], 2) for k in ("vlf", "lf", "hf"))],
        ["Power", "(n.u.)", "", _f(b["lf"]["powerNu"], 2), _f(b["hf"]["powerNu"], 2)],
        ["Total power", "(ms²)", _f(fft["totalPower"], 0), "", ""],
        ["Total power", "(log)", _f(fft["logTotalPower"], 3), "", ""],
        ["LF/HF ratio", "", _f(fft["lfHf"], 3), "", ""],
    ]
    _table(fig, 0.42, 0.500, rows, [0.088, 0.044, 0.07, 0.07, 0.07], size=7.2)
    spec = series["spectrum"]["fft"]
    ax = fig.add_axes((0.815, 0.375, 0.135, 0.125))
    fr, pw = spec["freqs"], [p / 1e6 for p in spec["power"]]  # ms²/Hz → s²/Hz
    ax.plot(fr, pw, color=INK, lw=0.6)
    for (lo, hi), c in (((0.0, 0.04), GREY), ((0.04, 0.15), ORANGE), ((0.15, 0.4), BLUE)):
        xs = [f for f in fr if lo <= f <= hi]
        ys = [pw[i] for i, f in enumerate(fr) if lo <= f <= hi]
        ax.fill_between(xs, ys, color=c, alpha=0.85, lw=0)
    ax.set_xlim(0, 0.5)
    ax.set_title("FFT spectrum", fontsize=7.4, pad=2)
    ax.set_xlabel("Frequency (Hz)", fontsize=6.5, color=MUTED, labelpad=1)
    ax.set_ylabel("Power (s²/Hz)", fontsize=6.5, color=MUTED, labelpad=1)
    _style(ax, 6)

    # ---- nonlinear
    nl = adv["nonlinear"]
    rq = nl.get("recurrence") or {}
    fig.text(0.05, 0.315, "Nonlinear results", fontsize=8.4, weight="bold", va="top")
    rows = [
        ["Variable", "Units", "Value"],
        ["Poincaré plot", "", ""],
        ["   SD1", "(ms)", _f(nl["sd1"], 1)],
        ["   SD2", "(ms)", _f(nl["sd2"], 1)],
        ["   SD2/SD1", "", _f(nl["sd2Sd1"], 3)],
        ["Approximate entropy (ApEn)", "", _f(nl["apen"], 3)],
        ["Sample entropy (SampEn)", "", _f(nl["sampen"], 3)],
        ["Detrended fluctuations (DFA)", "", ""],
        ["   DFA alpha1", "", _f(nl["dfaAlpha1"], 3)],
        ["   DFA alpha2", "", _f(nl["dfaAlpha2"], 3)],
        ["Recurrence plot", "", ""],
        ["   REC", "(%)", _f(rq.get("rec"), 2)],
        ["   DET", "(%)", _f(rq.get("det"), 2)],
        ["   Lmean / Lmax", "(beats)", f"{_f(rq.get('lmean'), 2)} / {_f(rq.get('lmax'))}"],
        ["   ShanEn", "", _f(rq.get("shanEn"), 3)],
    ]
    _table(fig, 0.05, 0.300, rows, [0.20, 0.06, 0.07])

    rr = smp["detrendedMs"]
    mean_rr = sum(smp["rrMs"]) / len(smp["rrMs"])
    ax = fig.add_axes((0.47, 0.118, 0.21, 0.177))
    xs, ys = [v + mean_rr for v in rr[:-1]], [v + mean_rr for v in rr[1:]]
    ax.plot(xs, ys, ".", ms=1.6, color=BLUE)
    lo, hi = min(xs + ys), max(xs + ys)
    ax.plot([lo, hi], [lo, hi], color=GREY, lw=0.5)
    if nl["sd1"] and nl["sd2"]:
        # SD2 along the identity line, SD1 across it (Tulppo et al. 1996).
        ax.add_patch(
            Ellipse(
                (mean_rr, mean_rr),
                2 * nl["sd2"],
                2 * nl["sd1"],
                angle=45,
                fill=False,
                ec=INK,
                lw=0.7,
            )
        )
    ax.set_title("Poincaré plot", fontsize=7.4, pad=2)
    ax.set_xlabel("RRn (ms)", fontsize=6.5, color=MUTED, labelpad=1)
    ax.set_ylabel("RRn+1 (ms)", fontsize=6.5, color=MUTED, labelpad=1)
    ax.set_aspect("equal", adjustable="datalim")
    _style(ax, 6)

    dfa = series.get("dfa", {})
    ax = fig.add_axes((0.75, 0.118, 0.20, 0.177))
    for key, color, label in (("short", ORANGE, "α1"), ("long", BLUE, "α2")):
        pts = dfa.get(key) or []
        if pts:
            ax.plot([p[0] for p in pts], [p[1] for p in pts], ".", ms=2.4, color=color)
            ax.text(
                pts[len(pts) // 2][0],
                pts[len(pts) // 2][1],
                f" {label}",
                fontsize=7,
                color=INK,
                va="bottom",
            )
    ax.set_title("Detrended fluctuations", fontsize=7.4, pad=2)
    ax.set_xlabel("log10 n (beats)", fontsize=6.5, color=MUTED, labelpad=1)
    ax.set_ylabel("log10 F(n)", fontsize=6.5, color=MUTED, labelpad=1)
    _style(ax, 6)

    fig.text(
        0.05, 0.078, "*Results are calculated from non-detrended RR data", fontsize=6.6, ha="left"
    )
    fig.add_artist(Line2D([0.05, 0.95], [0.066, 0.066], lw=1.0, color=GREY))
    fig.text(
        0.05, 0.055, f"{generated_at:%d-%b-%Y %H:%M:%S} UTC", fontsize=6.8, color=MUTED, va="top"
    )
    fig.text(0.5, 0.055, "Page 1", fontsize=6.8, color=MUTED, ha="center", va="top")
    fig.text(
        0.95,
        0.055,
        "NetriBeat · HRV analysis (Kubios-compatible definitions)",
        fontsize=6.8,
        color=MUTED,
        ha="right",
        va="top",
    )
    return _png(fig, dpi)


def _png(fig: Any, dpi: int) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=dpi)
    plt.close(fig)
    return buf.getvalue()
