import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { decimate, extent, nearest, ticks, useWidth } from './useWidth.js';

const M = { top: 12, right: 14, bottom: 30, left: 46 };
const NAV_H = 38; // overview strip under the chart
const ZOOM_STEP = 1.6;

/** Index range [i, j) of the sorted `xs` inside [lo, hi], plus one point either side. */
function sliceRange(xs, lo, hi) {
  if (!xs.length) return [0, 0];
  const i = Math.max(0, nearest(xs, lo) - 1);
  const j = Math.min(xs.length, nearest(xs, hi) + 2);
  return [i, j];
}

/**
 * Responsive SVG line chart with crosshair + tooltip, zoom and pan.
 *
 * Zoom: drag across the plot, the + / − buttons, Ctrl + mouse wheel, or the + / − keys.
 * Move: Shift + drag, the ◀ ▶ buttons, or the overview strip below (drag the window,
 * drag its edges to resize, click to jump). Reset: the Reset button, double-click or 0.
 *
 * series: [{ name, xs, ys, color, colorFor?(y) → css colour for zone-coloured lines, unit }]
 * bands:  [{ from, to, label, color }]   shaded x-ranges (e.g. HRV window)
 * markers:[{ x, y, label, title }]       points (e.g. R-peaks, artefacts)
 */
export default function LineChart({
  series, height = 220, xLabel, yLabel, xFormat = (v) => v, yFormat = (v) => v,
  bands = [], markers = [], yDomain, title, describe, zoomable = true,
}) {
  const [ref, width] = useWidth();
  const svgRef = useRef(null);
  const clipId = useId().replace(/:/g, '');
  const [cursor, setCursor] = useState(null);
  const [view, setView] = useState(null); // [lo, hi] of x, null = everything
  const [drag, setDrag] = useState(null); // { mode: 'select' | 'pan', x0, x1 | view0 }

  const full = series[0]?.xs || [];
  const [fx0, fx1] = full.length ? [full[0], full[full.length - 1]] : [0, 1];
  const span = fx1 - fx0 || 1;
  const minSpan = span / 500;
  const [x0, x1] = view || [fx0, fx1];
  const zoomed = view !== null;

  // Visible part of each series, thinned for speed (more detail as you zoom in).
  const data = useMemo(() => series.map((s) => {
    const [i, j] = sliceRange(s.xs, x0, x1);
    const [xs, ys] = decimate(s.xs.slice(i, j), s.ys.slice(i, j));
    return { ...s, xs, ys };
  }), [series, x0, x1]);
  const visibleMarkers = markers.filter((m) => m.x >= x0 && m.x <= x1);
  const all = data[0]?.xs || [];
  const markerYs = visibleMarkers.map((m) => m.y).filter((v) => Number.isFinite(v));
  const [y0, y1] = yDomain || extent([...data.flatMap((s) => s.ys), ...markerYs]);
  const w = width - M.left - M.right;
  const h = height - M.top - M.bottom;
  const sx = (v) => M.left + ((v - x0) / ((x1 - x0) || 1)) * w;
  const sy = (v) => M.top + h - ((v - y0) / ((y1 - y0) || 1)) * h;
  const toX = (px) => x0 + ((px - M.left) / w) * (x1 - x0);

  // ---- view changes (always kept inside the data and at least minSpan wide)
  const setRange = (lo, hi) => {
    let a = Math.min(lo, hi);
    let b = Math.max(lo, hi);
    if (b - a < minSpan) { const c = (a + b) / 2; a = c - minSpan / 2; b = c + minSpan / 2; }
    if (b - a >= span) { setView(null); return; }
    if (a < fx0) { b += fx0 - a; a = fx0; }
    if (b > fx1) { a -= b - fx1; b = fx1; }
    setView([a, b]);
    setCursor(null);
  };
  const zoomAt = (factor, center = (x0 + x1) / 2) => {
    const lo = center - (center - x0) * factor;
    setRange(lo, lo + (x1 - x0) * factor);
  };
  const panBy = (fraction) => setRange(x0 + (x1 - x0) * fraction, x1 + (x1 - x0) * fraction);

  // Ctrl + wheel zooms around the pointer (plain wheel keeps scrolling the page).
  useEffect(() => {
    const el = svgRef.current;
    if (!el || !zoomable) return undefined;
    const onWheel = (e) => {
      if (!e.ctrlKey && !e.metaKey) return;
      e.preventDefault();
      const px = e.clientX - el.getBoundingClientRect().left;
      zoomAt(e.deltaY > 0 ? ZOOM_STEP : 1 / ZOOM_STEP, toX(px));
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  });

  const paths = data.map((s) => {
    if (!s.colorFor) {
      const d = s.xs.map((x, i) => `${i ? 'L' : 'M'}${sx(x).toFixed(1)},${sy(s.ys[i]).toFixed(1)}`).join('');
      return [{ d, color: s.color }];
    }
    const segs = [];
    let cur = null;
    s.xs.forEach((x, i) => {
      const c = s.colorFor(s.ys[i]);
      const pt = `${sx(x).toFixed(1)},${sy(s.ys[i]).toFixed(1)}`;
      if (!cur || cur.color !== c) {
        const start = cur ? cur.last : null;
        cur = { color: c, d: start ? `M${start}L${pt}` : `M${pt}`, last: pt };
        segs.push(cur);
      } else {
        cur.d += `L${pt}`;
        cur.last = pt;
      }
    });
    return segs;
  });

  // ---- pointer: crosshair, drag-to-zoom, shift-drag to pan
  const localX = (e) => e.clientX - e.currentTarget.getBoundingClientRect().left;
  const onPointerDown = (e) => {
    if (!zoomable || e.button !== 0) return;
    const px = localX(e);
    if (px < M.left || px > M.left + w) return;
    e.currentTarget.setPointerCapture(e.pointerId);
    setDrag(e.shiftKey && zoomed ? { mode: 'pan', start: px, view0: [x0, x1] } : { mode: 'select', a: px, b: px });
  };
  const onPointerMove = (e) => {
    const px = localX(e);
    if (drag?.mode === 'select') setDrag({ ...drag, b: Math.max(M.left, Math.min(M.left + w, px)) });
    else if (drag?.mode === 'pan') {
      const dx = ((drag.start - px) / w) * (drag.view0[1] - drag.view0[0]);
      setRange(drag.view0[0] + dx, drag.view0[1] + dx);
    } else if (all.length) setCursor(nearest(all, toX(px)));
  };
  const onPointerUp = () => {
    if (drag?.mode === 'select' && Math.abs(drag.b - drag.a) > 6) setRange(toX(drag.a), toX(drag.b));
    setDrag(null);
  };

  const onKey = (e) => {
    if (zoomable && (e.key === '+' || e.key === '=')) zoomAt(1 / ZOOM_STEP);
    else if (zoomable && (e.key === '-' || e.key === '_')) zoomAt(ZOOM_STEP);
    else if (zoomable && e.key === '0') setView(null);
    else if (zoomable && e.key === 'PageDown') panBy(0.5);
    else if (zoomable && e.key === 'PageUp') panBy(-0.5);
    else if (all.length && e.key === 'ArrowRight') {
      const stepBy = e.shiftKey ? Math.max(1, Math.round(all.length / 20)) : 1;
      setCursor((c) => Math.min(all.length - 1, (c ?? -1) + stepBy));
    } else if (all.length && e.key === 'ArrowLeft') {
      const stepBy = e.shiftKey ? Math.max(1, Math.round(all.length / 20)) : 1;
      setCursor((c) => Math.max(0, (c ?? all.length) - stepBy));
    } else if (e.key === 'Escape') setCursor(null);
    else return;
    e.preventDefault();
  };

  const idx = cursor === null || !all.length || drag ? null : Math.min(cursor, all.length - 1);
  const tipLeft = idx !== null ? Math.min(sx(all[idx]) + 10, width - 170) : 0;

  return (
    <div className="nb-chart" ref={ref}>
      {zoomable && full.length > 2 ? (
        <div className="nb-chart-tools" role="group" aria-label={`${title || 'Chart'} zoom`}>
          <span className="nb-chart-range">{zoomed ? `${xFormat(x0)} – ${xFormat(x1)}` : 'Drag across the chart to zoom'}</span>
          <button type="button" onClick={() => panBy(-0.5)} disabled={!zoomed || x0 <= fx0} aria-label="Move left" title="Move left">◀</button>
          <button type="button" onClick={() => panBy(0.5)} disabled={!zoomed || x1 >= fx1} aria-label="Move right" title="Move right">▶</button>
          <button type="button" onClick={() => zoomAt(1 / ZOOM_STEP)} aria-label="Zoom in" title="Zoom in (+)">+</button>
          <button type="button" onClick={() => zoomAt(ZOOM_STEP)} disabled={!zoomed} aria-label="Zoom out" title="Zoom out (−)">−</button>
          <button type="button" onClick={() => setView(null)} disabled={!zoomed} title="Show everything (0)">Reset</button>
        </div>
      ) : null}
      <svg
        ref={svgRef} width={width} height={height} role="img" tabIndex={0}
        className={zoomable ? (drag?.mode === 'pan' ? 'is-panning' : 'is-zoomable') : undefined}
        aria-label={`${title || 'Chart'}${describe ? `: ${describe}` : ''}. Arrow keys read values; + and − zoom; Page Up and Page Down move; 0 resets.`}
        onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp}
        onPointerCancel={() => setDrag(null)} onDoubleClick={() => zoomable && setView(null)}
        onPointerLeave={() => !drag && setCursor(null)} onBlur={() => setCursor(null)} onKeyDown={onKey}
      >
        <defs><clipPath id={clipId}><rect x={M.left} y={M.top - 6} width={w} height={h + 12} /></clipPath></defs>
        {bands.filter((b) => b.to > x0 && b.from < x1).map((b) => (
          <g key={`${b.from}-${b.to}`}>
            <rect x={sx(Math.max(b.from, x0))} y={M.top} width={Math.max(0, sx(Math.min(b.to, x1)) - sx(Math.max(b.from, x0)))} height={h} fill={b.color || 'var(--accent)'} opacity="0.08" />
            {b.label ? <text x={sx(Math.max(b.from, x0)) + 4} y={M.top + 11} className="nb-chart-band-label" fill={b.color || 'var(--ink-muted)'}>{b.label}</text> : null}
          </g>
        ))}
        {ticks(y0, y1).map((t) => (
          <g key={`y${t}`}>
            <line x1={M.left} x2={M.left + w} y1={sy(t)} y2={sy(t)} className="nb-chart-grid" />
            <text x={M.left - 6} y={sy(t) + 4} textAnchor="end" className="nb-chart-tick">{yFormat(t)}</text>
          </g>
        ))}
        {ticks(x0, x1, Math.max(2, Math.floor(w / 90))).map((t) => (
          <text key={`x${t}`} x={sx(t)} y={height - 10} textAnchor="middle" className="nb-chart-tick">{xFormat(t)}</text>
        ))}
        {yLabel ? <text x={12} y={M.top + h / 2} transform={`rotate(-90 12 ${M.top + h / 2})`} textAnchor="middle" className="nb-chart-tick">{yLabel}</text> : null}
        {xLabel ? <text x={M.left + w} y={height - 10} textAnchor="end" className="nb-chart-tick nb-chart-xlabel">{xLabel}</text> : null}
        <g clipPath={`url(#${clipId})`}>
          {paths.map((segs, si) => segs.map((p, pi) => (
            // eslint-disable-next-line react/no-array-index-key
            <path key={`${si}-${pi}`} d={p.d} fill="none" stroke={p.color} strokeWidth="1.6" strokeLinejoin="round" />
          )))}
          {visibleMarkers.map((mk, i) => (
            // eslint-disable-next-line react/no-array-index-key
            <g key={i}>
              <circle cx={sx(mk.x)} cy={sy(mk.y)} r={mk.r || 3.2} fill={mk.fill || 'none'} stroke={mk.color || 'var(--zone-5)'} strokeWidth="1.5">
                {mk.title ? <title>{mk.title}</title> : null}
              </circle>
              {mk.label ? <text x={sx(mk.x)} y={sy(mk.y) - 7} textAnchor="middle" className="nb-chart-mark-label">{mk.label}</text> : null}
            </g>
          ))}
        </g>
        {drag?.mode === 'select' && Math.abs(drag.b - drag.a) > 1 ? (
          <rect x={Math.min(drag.a, drag.b)} y={M.top} width={Math.abs(drag.b - drag.a)} height={h} className="nb-chart-select" />
        ) : null}
        {idx !== null ? (
          <g pointerEvents="none">
            <line x1={sx(all[idx])} x2={sx(all[idx])} y1={M.top} y2={M.top + h} className="nb-chart-cross" />
            {data.map((s) => (s.ys[idx] !== undefined && s.ys[idx] !== null ? (
              <circle key={s.name} cx={sx(s.xs[idx])} cy={sy(s.ys[idx])} r="3.5" fill={s.colorFor ? s.colorFor(s.ys[idx]) : s.color} />
            ) : null))}
          </g>
        ) : null}
      </svg>
      {zoomable && zoomed ? (
        <Navigator series={series[0]} width={width} range={[fx0, fx1]} view={[x0, x1]} onChange={setRange} />
      ) : null}
      {idx !== null ? (
        <div className="nb-tooltip" style={{ left: tipLeft, top: M.top + 28 }} role="status">
          <div className="nb-tooltip-x">{xLabel ? `${xLabel}: ` : ''}{xFormat(all[idx])}</div>
          {data.map((s) => (
            <div key={s.name}><span className="nb-swatch" style={{ background: s.colorFor ? s.colorFor(s.ys[idx]) : s.color }} />{s.name}: <b>{yFormat(s.ys[idx])}</b>{s.unit ? ` ${s.unit}` : ''}</div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

/** Overview of the whole series with the visible window: drag it, drag its edges, or click. */
function Navigator({ series, width, range, view, onChange }) {
  const [drag, setDrag] = useState(null); // { mode: 'move' | 'left' | 'right', start, view0 }
  const [fx0, fx1] = range;
  const w = width - M.left - M.right;
  const sx = (v) => M.left + ((v - fx0) / ((fx1 - fx0) || 1)) * w;
  const toX = (px) => fx0 + ((px - M.left) / w) * (fx1 - fx0);
  const [xs, ys] = useMemo(() => decimate(series.xs, series.ys, 600), [series]);
  const [y0, y1] = extent(ys);
  const sy = (v) => 4 + (NAV_H - 8) * (1 - (v - y0) / ((y1 - y0) || 1));
  const d = xs.map((x, i) => `${i ? 'L' : 'M'}${sx(x).toFixed(1)},${sy(ys[i]).toFixed(1)}`).join('');
  const a = sx(view[0]);
  const b = sx(view[1]);

  const localX = (e) => e.clientX - e.currentTarget.getBoundingClientRect().left;
  const onDown = (e) => {
    const px = localX(e);
    e.currentTarget.setPointerCapture(e.pointerId);
    if (Math.abs(px - a) < 7) setDrag({ mode: 'left', start: px, view0: view });
    else if (Math.abs(px - b) < 7) setDrag({ mode: 'right', start: px, view0: view });
    else if (px > a && px < b) setDrag({ mode: 'move', start: px, view0: view });
    else { // click outside the window: centre the window there
      const half = (view[1] - view[0]) / 2;
      const c = toX(px);
      onChange(c - half, c + half);
      setDrag({ mode: 'move', start: px, view0: [c - half, c + half] });
    }
  };
  const onMove = (e) => {
    if (!drag) return;
    const dx = ((localX(e) - drag.start) / w) * (fx1 - fx0);
    const [l, r] = drag.view0;
    if (drag.mode === 'move') onChange(l + dx, r + dx);
    else if (drag.mode === 'left') onChange(Math.min(l + dx, r), r);
    else onChange(l, Math.max(r + dx, l));
  };

  return (
    <svg
      width={width} height={NAV_H} className="nb-chart-nav" aria-hidden="true"
      onPointerDown={onDown} onPointerMove={onMove} onPointerUp={() => setDrag(null)} onPointerCancel={() => setDrag(null)}
    >
      <rect x={M.left} y={0} width={w} height={NAV_H} className="nb-chart-nav-bg" />
      <path d={d} fill="none" stroke={series.color} strokeWidth="1" opacity="0.7" />
      <rect x={M.left} y={0} width={Math.max(0, a - M.left)} height={NAV_H} className="nb-chart-nav-shade" />
      <rect x={b} y={0} width={Math.max(0, M.left + w - b)} height={NAV_H} className="nb-chart-nav-shade" />
      <rect x={a} y={0.5} width={Math.max(2, b - a)} height={NAV_H - 1} className="nb-chart-nav-window" />
      <rect x={a - 3} y={NAV_H / 2 - 9} width={6} height={18} rx={2} className="nb-chart-nav-handle" />
      <rect x={b - 3} y={NAV_H / 2 - 9} width={6} height={18} rx={2} className="nb-chart-nav-handle" />
    </svg>
  );
}
