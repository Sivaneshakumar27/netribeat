import { TYPE_COLOR, TYPE_LABEL } from '../utils/session.js';

// Shape differs, not just colour (design-spec §4): dot, triangle, ring.
const Q = {
  good: ['Good', 'nb-q-good', <circle key="d" cx="6" cy="6" r="4" fill="currentColor" />],
  poor: ['Poor', 'nb-q-poor', <path key="t" d="M6 1.5 11 10.5H1z" fill="currentColor" />],
  no_ecg: ['No ECG', 'nb-q-none', <circle key="r" cx="6" cy="6" r="4" fill="none" stroke="currentColor" strokeWidth="1.6" />],
};

export function QualityBadge({ quality, reliable }) {
  if (!quality) return <span className="nb-muted">—</span>;
  const [label, cls, shape] = Q[quality] || [quality, '', null];
  return (
    <span className="nb-q-wrap">
      <span className={`nb-q ${cls}`}><svg width="12" height="12" aria-hidden="true">{shape}</svg>{label}</span>
      {reliable === false ? <span className="nb-q nb-q-warn" title="Beat detection unreliable">Unreliable</span> : null}
    </span>
  );
}

export function StatusBadge({ status }) {
  const map = { processing: ['Processing', 'nb-badge'], ready: ['Ready', 'nb-badge nb-badge-ok'], failed: ['Failed', 'nb-badge nb-badge-off'] };
  const [label, cls] = map[status] || [status, 'nb-badge'];
  return <span className={cls}>{status === 'processing' ? <span className="nb-spinner nb-spinner-sm" aria-hidden="true" /> : null}{label}</span>;
}

export function TypePill({ type }) {
  return <span className="nb-type"><span className="nb-type-dot" style={{ background: TYPE_COLOR[type] }} />{TYPE_LABEL[type] || type}</span>;
}

export function MetricTile({ label, value, unit, sub, tone }) {
  return (
    <div className={`nb-tile${tone ? ` nb-tile-${tone}` : ''}`}>
      <div className="nb-tile-label">{label}</div>
      <div className="nb-tile-value">{value}{unit && value !== '—' ? <span className="nb-tile-unit"> {unit}</span> : null}</div>
      {sub ? <div className="nb-tile-sub">{sub}</div> : null}
    </div>
  );
}
