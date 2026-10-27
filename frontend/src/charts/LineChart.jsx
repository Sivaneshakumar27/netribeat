import { useMemo, useState } from 'react';
import { decimate, extent, nearest, ticks, useWidth } from './useWidth.js';

const M = { top: 12, right: 14, bottom: 30, left: 46 };

/**
 * Responsive SVG line chart with crosshair + tooltip (mouse, touch and keyboard).
 * series: [{ name, xs, ys, color, colorFor?(y) → css colour for zone-coloured lines, unit }]
 * bands:  [{ from, to, label, color }]   shaded x-ranges (e.g. HRV window)
 * markers:[{ x, y, label }]               points (e.g. R-peaks, artefacts)
 */
export default function LineChart({
  series, height = 220, xLabel, yLabel, xFormat = (v) => v, yFormat = (v) => v,
  bands = [], markers = [], yDomain, title, describe,
}) {
  const [ref, width] = useWidth();
  const [cursor, setCursor] = useState(null);
  const data = useMemo(() => series.map((s) => {
    const [xs, ys] = decimate(s.xs, s.ys);
    return { ...s, xs, ys };
  }), [series]);
  const all = data[0]?.xs || [];
  const [x0, x1] = all.length ? [all[0], all[all.length - 1]] : [0, 1];
  // Markers (e.g. artefacts at their raw value) are part of the range, so none fall outside the plot.
  const markerYs = markers.map((m) => m.y).filter((v) => Number.isFinite(v));
  const [y0, y1] = yDomain || extent([...data.flatMap((s) => s.ys), ...markerYs]);
  const w = width - M.left - M.right;
  const h = height - M.top - M.bottom;
  const sx = (v) => M.left + ((v - x0) / ((x1 - x0) || 1)) * w;
  const sy = (v) => M.top + h - ((v - y0) / ((y1 - y0) || 1)) * h;

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

  const idx = cursor === null || !all.length ? null : cursor;
  const move = (clientX, rect) => {
    if (!all.length) return;
    const x = x0 + ((clientX - rect.left - M.left) / w) * (x1 - x0);
    setCursor(nearest(all, x));
  };
  const onKey = (e) => {
    if (!all.length) return;
    const stepBy = e.shiftKey ? Math.max(1, Math.round(all.length / 20)) : 1;
    if (e.key === 'ArrowRight') setCursor((c) => Math.min(all.length - 1, (c ?? -1) + stepBy));
    else if (e.key === 'ArrowLeft') setCursor((c) => Math.max(0, (c ?? all.length) - stepBy));
    else if (e.key === 'Escape') setCursor(null);
    else return;
    e.preventDefault();
  };

  const tipLeft = idx !== null ? Math.min(sx(all[idx]) + 10, width - 170) : 0;
  return (
    <div className="nb-chart" ref={ref}>
      <svg
        width={width} height={height} role="img" tabIndex={0}
        aria-label={`${title || 'Chart'}${describe ? `: ${describe}` : ''}. Use left and right arrow keys to read values.`}
        onMouseMove={(e) => move(e.clientX, e.currentTarget.getBoundingClientRect())}
        onTouchMove={(e) => move(e.touches[0].clientX, e.currentTarget.getBoundingClientRect())}
        onMouseLeave={() => setCursor(null)} onBlur={() => setCursor(null)} onKeyDown={onKey}
      >
        {bands.map((b) => (
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
        {paths.map((segs, si) => segs.map((p, pi) => (
          // eslint-disable-next-line react/no-array-index-key
          <path key={`${si}-${pi}`} d={p.d} fill="none" stroke={p.color} strokeWidth="1.6" strokeLinejoin="round" />
        )))}
        {markers.map((mk, i) => (
          // eslint-disable-next-line react/no-array-index-key
          <g key={i}>
            <circle cx={sx(mk.x)} cy={sy(mk.y)} r={mk.r || 3.2} fill={mk.fill || 'none'} stroke={mk.color || 'var(--zone-5)'} strokeWidth="1.5">
              {mk.title ? <title>{mk.title}</title> : null}
            </circle>
            {mk.label ? <text x={sx(mk.x)} y={sy(mk.y) - 7} textAnchor="middle" className="nb-chart-mark-label">{mk.label}</text> : null}
          </g>
        ))}
        {idx !== null ? (
          <g pointerEvents="none">
            <line x1={sx(all[idx])} x2={sx(all[idx])} y1={M.top} y2={M.top + h} className="nb-chart-cross" />
            {data.map((s) => (s.ys[idx] !== undefined && s.ys[idx] !== null ? (
              <circle key={s.name} cx={sx(s.xs[idx])} cy={sy(s.ys[idx])} r="3.5" fill={s.colorFor ? s.colorFor(s.ys[idx]) : s.color} />
            ) : null))}
          </g>
        ) : null}
      </svg>
      {idx !== null ? (
        <div className="nb-tooltip" style={{ left: tipLeft, top: M.top }} role="status">
          <div className="nb-tooltip-x">{xLabel ? `${xLabel}: ` : ''}{xFormat(all[idx])}</div>
          {data.map((s) => (
            <div key={s.name}><span className="nb-swatch" style={{ background: s.colorFor ? s.colorFor(s.ys[idx]) : s.color }} />{s.name}: <b>{yFormat(s.ys[idx])}</b>{s.unit ? ` ${s.unit}` : ''}</div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
