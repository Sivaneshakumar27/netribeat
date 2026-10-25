import { useState } from 'react';
import { extent, ticks, useWidth } from './useWidth.js';

const M = { top: 12, right: 12, bottom: 30, left: 44 };

/** Bars with a dashed mean line and hover/keyboard tooltip.
 *  items: [{ label, value, color, sub }] */
export default function BarChart({ items, height = 200, unit = '', title, valueFormat = (v) => v.toFixed(0) }) {
  const [ref, width] = useWidth();
  const [hover, setHover] = useState(null);
  const values = items.map((i) => i.value).filter((v) => v !== null && v !== undefined);
  const [, hi] = extent([0, ...values], 0.1);
  const w = width - M.left - M.right;
  const h = height - M.top - M.bottom;
  const bw = items.length ? w / items.length : w;
  const sy = (v) => M.top + h - (v / (hi || 1)) * h;
  const mean = values.length ? values.reduce((a, b) => a + b, 0) / values.length : null;
  return (
    <div className="nb-chart" ref={ref}>
      <svg width={width} height={height} role="img" tabIndex={0} aria-label={`${title}. ${items.length} sessions${mean !== null ? `, mean ${valueFormat(mean)} ${unit}` : ''}.`}
        onKeyDown={(e) => {
          if (e.key === 'ArrowRight') setHover((x) => Math.min(items.length - 1, (x ?? -1) + 1));
          else if (e.key === 'ArrowLeft') setHover((x) => Math.max(0, (x ?? items.length) - 1));
          else return;
          e.preventDefault();
        }} onBlur={() => setHover(null)} onMouseLeave={() => setHover(null)}>
        {ticks(0, hi, 4).map((t) => (
          <g key={t}>
            <line x1={M.left} x2={M.left + w} y1={sy(t)} y2={sy(t)} className="nb-chart-grid" />
            <text x={M.left - 6} y={sy(t) + 4} textAnchor="end" className="nb-chart-tick">{t}</text>
          </g>
        ))}
        {items.map((it, i) => (it.value === null || it.value === undefined ? null : (
          <rect key={it.label + i} x={M.left + i * bw + bw * 0.18} width={bw * 0.64} y={sy(it.value)} height={M.top + h - sy(it.value)}
            fill={it.color || 'var(--accent-fill)'} opacity={hover === null || hover === i ? 1 : 0.45} rx="2"
            onMouseEnter={() => setHover(i)} />
        )))}
        {mean !== null ? <line x1={M.left} x2={M.left + w} y1={sy(mean)} y2={sy(mean)} className="nb-chart-mean" /> : null}
        {items.map((it, i) => (items.length <= 14 ? (
          <text key={`l${it.label}${i}`} x={M.left + i * bw + bw / 2} y={height - 10} textAnchor="middle" className="nb-chart-tick">{it.label}</text>
        ) : null))}
      </svg>
      {hover !== null && items[hover] ? (
        <div className="nb-tooltip" style={{ left: Math.min(M.left + hover * bw + bw / 2, width - 170), top: M.top }} role="status">
          <div className="nb-tooltip-x">{items[hover].sub || items[hover].label}</div>
          <div><b>{items[hover].value === null ? 'n/a' : valueFormat(items[hover].value)}</b> {unit}</div>
        </div>
      ) : null}
    </div>
  );
}
