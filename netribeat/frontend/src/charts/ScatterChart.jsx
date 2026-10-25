import { extent, ticks, useWidth } from './useWidth.js';

const M = { top: 12, right: 12, bottom: 34, left: 46 };

/** Scatter of point groups, each with its own colour and an optional fitted line label. */
export default function ScatterChart({ groups, height = 240, xLabel, yLabel, title, describe }) {
  const [ref, width] = useWidth(360);
  const pts = groups.flatMap((g) => g.points);
  const [x0, x1] = extent(pts.map((p) => p[0]));
  const [y0, y1] = extent(pts.map((p) => p[1]));
  const w = width - M.left - M.right;
  const h = height - M.top - M.bottom;
  const sx = (v) => M.left + ((v - x0) / (x1 - x0)) * w;
  const sy = (v) => M.top + h - ((v - y0) / (y1 - y0)) * h;
  return (
    <div className="nb-chart" ref={ref}>
      <svg width={width} height={height} role="img" aria-label={`${title}${describe ? `: ${describe}` : ''}`}>
        {ticks(y0, y1, 4).map((t) => (
          <g key={`y${t}`}>
            <line x1={M.left} x2={M.left + w} y1={sy(t)} y2={sy(t)} className="nb-chart-grid" />
            <text x={M.left - 6} y={sy(t) + 4} textAnchor="end" className="nb-chart-tick">{t.toFixed(2)}</text>
          </g>
        ))}
        {ticks(x0, x1, 5).map((t) => <text key={`x${t}`} x={sx(t)} y={height - 16} textAnchor="middle" className="nb-chart-tick">{t.toFixed(2)}</text>)}
        {groups.map((g) => g.points.map((p, i) => (
          // eslint-disable-next-line react/no-array-index-key
          <circle key={`${g.name}${i}`} cx={sx(p[0])} cy={sy(p[1])} r="2.6" fill={g.color} />
        )))}
        {groups.map((g) => (g.points.length ? (
          <text key={`l${g.name}`} x={sx(g.points[Math.floor(g.points.length / 2)][0]) + 6} y={sy(g.points[Math.floor(g.points.length / 2)][1]) - 6} className="nb-chart-band-label" fill={g.color}>{g.label}</text>
        ) : null))}
        {xLabel ? <text x={M.left + w} y={height - 2} textAnchor="end" className="nb-chart-tick">{xLabel}</text> : null}
        {yLabel ? <text x={12} y={M.top + h / 2} transform={`rotate(-90 12 ${M.top + h / 2})`} textAnchor="middle" className="nb-chart-tick">{yLabel}</text> : null}
      </svg>
    </div>
  );
}
