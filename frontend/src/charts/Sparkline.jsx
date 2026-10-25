/** Tiny inline trend line. `null` values leave a gap. */
export default function Sparkline({ values, width = 160, height = 36, color = 'var(--accent)', label }) {
  const nums = values.filter((v) => v !== null && v !== undefined);
  if (nums.length < 2) return <span className="nb-muted nb-small">Not enough data</span>;
  const lo = Math.min(...nums);
  const hi = Math.max(...nums);
  const sx = (i) => (i / (values.length - 1)) * (width - 4) + 2;
  const sy = (v) => height - 3 - ((v - lo) / ((hi - lo) || 1)) * (height - 6);
  let d = '';
  values.forEach((v, i) => {
    if (v === null || v === undefined) return;
    d += `${d && values[i - 1] !== null && values[i - 1] !== undefined ? 'L' : 'M'}${sx(i).toFixed(1)},${sy(v).toFixed(1)}`;
  });
  return (
    <svg width={width} height={height} role="img" aria-label={label || `Trend from ${lo.toFixed(1)} to ${hi.toFixed(1)}`}>
      <path d={d} fill="none" stroke={color} strokeWidth="1.6" />
    </svg>
  );
}
