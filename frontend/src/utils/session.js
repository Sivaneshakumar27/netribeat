export const SESSION_TYPES = [
  ['training', 'Training'], ['rest', 'Rest / baseline'], ['match', 'Match / competition'],
  ['recovery', 'Recovery'], ['test', 'Test protocol'],
];
export const DEVICES = [
  ['synapse', 'Synapse sensor (hex)'], ['chest_strap_rr', 'Chest strap (RR only)'], ['chest_strap_rr_acc', 'Chest strap (RR + ACC)'],
  ['ecg_holter', 'ECG Holter'], ['optical_wrist', 'Optical wrist sensor'], ['other', 'Other'],
];
export const TYPE_LABEL = Object.fromEntries(SESSION_TYPES);
export const DEVICE_LABEL = Object.fromEntries(DEVICES);
export const TYPE_COLOR = {
  training: 'var(--accent-fill)', rest: 'var(--zone-2)', match: 'var(--zone-5)',
  recovery: 'var(--zone-3)', test: 'var(--zone-4)',
};

export function duration(s) {
  if (s === null || s === undefined) return '—';
  const total = Math.round(s);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const sec = total % 60;
  return h ? `${h}h ${String(m).padStart(2, '0')}m` : `${m}:${String(sec).padStart(2, '0')}`;
}

export const num = (v, digits = 0, unit = '') => (v === null || v === undefined || Number.isNaN(v)
  ? '—' : `${Number(v).toFixed(digits)}${unit ? ` ${unit}` : ''}`);

/** Zone colour for a bpm value at a given HRmax (design-spec §6 boundaries). */
export function zoneColor(bpm, hrMax) {
  if (!hrMax) return 'var(--accent)';
  const p = (bpm / hrMax) * 100;
  if (p >= 90) return 'var(--zone-5)';
  if (p >= 80) return 'var(--zone-4)';
  if (p >= 70) return 'var(--zone-3)';
  if (p >= 60) return 'var(--zone-2)';
  if (p >= 50) return 'var(--zone-1)';
  return 'var(--line-strong)';
}

export const mmss = (t) => `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, '0')}`;
