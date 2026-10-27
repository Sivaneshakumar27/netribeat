const ZONES = [
  ['z5', 'Z5', '≥ 90 %', 'var(--zone-5)'], ['z4', 'Z4', '80–90 %', 'var(--zone-4)'],
  ['z3', 'Z3', '70–80 %', 'var(--zone-3)'], ['z2', 'Z2', '60–70 %', 'var(--zone-2)'],
  ['z1', 'Z1', '50–60 %', 'var(--zone-1)'], ['belowZ1', 'Below', '< 50 %', 'var(--line-strong)'],
];

const fmt = (s) => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`;

/** Time-in-zone distribution (Z5 → below Z1) with bpm ranges when HRmax is known. */
export default function ZoneBars({ timeInZonesS, hrMax, reason }) {
  if (!timeInZonesS) return <p className="nb-muted">Zones unavailable{reason ? `: ${reason}` : '.'}</p>;
  const total = Object.values(timeInZonesS).reduce((a, b) => a + b, 0) || 1;
  const edges = { z5: [0.9, null], z4: [0.8, 0.9], z3: [0.7, 0.8], z2: [0.6, 0.7], z1: [0.5, 0.6], belowZ1: [null, 0.5] };
  return (
    <ul className="nb-zones" aria-label="Time in heart-rate zones">
      {ZONES.map(([key, name, pct, color]) => {
        const s = timeInZonesS[key] || 0;
        const [a, b] = edges[key];
        const range = hrMax ? `${a ? Math.round(a * hrMax) : '<'}${a && b ? '–' : ''}${b ? Math.round(b * hrMax) : '+'} bpm` : pct;
        return (
          <li key={key}>
            <span className="nb-zone-name" style={{ color }}>{name}</span>
            <span className="nb-zone-range nb-muted nb-small">{range}</span>
            <span className="nb-zone-track"><span style={{ width: `${(s / total) * 100}%`, background: color }} /></span>
            <span className="nb-zone-val">{fmt(s)} <span className="nb-muted nb-small">{((s / total) * 100).toFixed(0)} %</span></span>
          </li>
        );
      })}
    </ul>
  );
}
