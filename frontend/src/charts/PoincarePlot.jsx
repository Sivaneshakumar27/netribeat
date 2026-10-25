import { extent, ticks, useWidth } from './useWidth.js';

const M = { top: 12, right: 12, bottom: 34, left: 50 };

/** Poincaré plot: RRn vs RRn+1, identity line and the SD1/SD2 ellipse. */
export default function PoincarePlot({ rr, sd1, sd2 }) {
  const [ref, width] = useWidth(360);
  const size = Math.min(width, 380);
  const [lo, hi] = extent(rr, 0.08);
  const w = size - M.left - M.right;
  const h = size - M.top - M.bottom;
  const sx = (v) => M.left + ((v - lo) / (hi - lo)) * w;
  const sy = (v) => M.top + h - ((v - lo) / (hi - lo)) * h;
  const mean = rr.reduce((a, b) => a + b, 0) / (rr.length || 1);
  const pts = [];
  for (let i = 0; i + 1 < rr.length && pts.length < 3000; i += 1) pts.push([rr[i], rr[i + 1]]);
  const scale = w / (hi - lo);
  return (
    <div className="nb-chart" ref={ref}>
      <svg width={size} height={size} role="img" aria-label={`Poincaré plot of ${pts.length} beat pairs. SD1 ${sd1?.toFixed(1)} ms, SD2 ${sd2?.toFixed(1)} ms.`}>
        {ticks(lo, hi, 4).map((t) => (
          <g key={t}>
            <line x1={sx(t)} x2={sx(t)} y1={M.top} y2={M.top + h} className="nb-chart-grid" />
            <line x1={M.left} x2={M.left + w} y1={sy(t)} y2={sy(t)} className="nb-chart-grid" />
            <text x={sx(t)} y={size - 16} textAnchor="middle" className="nb-chart-tick">{Math.round(t)}</text>
            <text x={M.left - 6} y={sy(t) + 4} textAnchor="end" className="nb-chart-tick">{Math.round(t)}</text>
          </g>
        ))}
        <line x1={sx(lo)} y1={sy(lo)} x2={sx(hi)} y2={sy(hi)} className="nb-chart-mean" />
        {pts.map(([a, b], i) => (
          // eslint-disable-next-line react/no-array-index-key
          <circle key={i} cx={sx(a)} cy={sy(b)} r="1.8" fill="var(--band-hf)" opacity="0.55" />
        ))}
        {sd1 && sd2 ? (
          <ellipse cx={sx(mean)} cy={sy(mean)} rx={sd2 * scale} ry={sd1 * scale}
            transform={`rotate(-45 ${sx(mean)} ${sy(mean)})`} fill="none" stroke="var(--accent)" strokeWidth="1.8" />
        ) : null}
        <text x={M.left + w} y={size - 2} textAnchor="end" className="nb-chart-tick">RRₙ (ms)</text>
        <text x={12} y={M.top + h / 2} transform={`rotate(-90 12 ${M.top + h / 2})`} textAnchor="middle" className="nb-chart-tick">RRₙ₊₁ (ms)</text>
      </svg>
    </div>
  );
}
