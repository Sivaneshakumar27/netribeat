import { useCallback, useEffect, useState } from 'react';
import { ApiError, adminApi, sessionsApi } from '../api/client.js';
import { useAuth } from '../auth/AuthContext.jsx';
import { Alert, Button } from '../components/ui.jsx';

const ROWS = [['Z5', 0.9, null, 'var(--zone-5)'], ['Z4', 0.8, 0.9, 'var(--zone-4)'], ['Z3', 0.7, 0.8, 'var(--zone-3)'],
  ['Z2', 0.6, 0.7, 'var(--zone-2)'], ['Z1', 0.5, 0.6, 'var(--zone-1)']];
const LABEL = { age: 'Age-based', peak: 'Session peaks', manual: 'Manual' };

export default function SettingsPage() {
  const { user } = useAuth();
  const admin = user.role === 'admin';
  const [target, setTarget] = useState('');
  const [users, setUsers] = useState([]);
  const [data, setData] = useState(null);
  const [method, setMethod] = useState(null);
  const [manual, setManual] = useState('');
  const [msg, setMsg] = useState(null);
  const [fieldErr, setFieldErr] = useState({});
  const [busy, setBusy] = useState(false);

  useEffect(() => { if (admin) adminApi.listUsers({ limit: 200, sort: 'email' }).then((r) => setUsers(r.items)).catch(() => {}); }, [admin]);
  const load = useCallback(async () => {
    const r = target ? await sessionsApi.userHrMax(target) : await sessionsApi.hrMax();
    setData(r);
    setMethod(r.method);
    setManual(r.manualValue ? String(r.manualValue) : '');
  }, [target]);
  useEffect(() => { load().catch((e) => setMsg({ tone: 'error', text: e.message })); }, [load]);

  if (!data) return <div className="nb-loading-inline" role="status"><span className="nb-spinner" aria-hidden="true" /> Loading…</div>;
  const manualNum = Number(manual);
  const manualOk = manual !== '' && manualNum >= 100 && manualNum <= 230;
  const values = Object.fromEntries(data.options.map((o) => [o.method, o]));
  const preview = method === 'manual' ? (manualOk ? manualNum : null) : values[method]?.value ?? null;
  const changed = method !== data.method || (method === 'manual' && manualNum !== data.manualValue);
  const valid = method && (method !== 'manual' || manualOk) && (method !== 'peak' || values.peak.value);

  async function save() {
    setBusy(true);
    setMsg(null);
    setFieldErr({});
    try {
      const body = { method, manualValue: method === 'manual' ? manualNum : null };
      const r = target ? await sessionsApi.setUserHrMax(target, body) : await sessionsApi.setHrMax(body);
      setData(r);
      setMsg({ tone: 'success', text: `Saved · ${r.effective?.value ?? '—'} bpm. ${r.recomputedSessions} session${r.recomputedSessions === 1 ? '' : 's'} recalculated.` });
    } catch (e) {
      if (e instanceof ApiError && e.code === 'validation_error') setFieldErr(e.fields);
      setMsg({ tone: 'error', text: e.message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <header className="nb-page-head"><div><h1 className="nb-page-title">Analysis settings</h1>
        <p className="nb-muted">Max HR drives heart-rate zones, the zone split and training load for every session of {target ? 'this user' : 'yours'}.</p></div></header>
      {admin ? (
        <div className="nb-field nb-narrow">
          <label className="nb-field-label" htmlFor="set-user">User</label>
          <select id="set-user" className="nb-input" value={target} onChange={(e) => { setTarget(e.target.value); setMsg(null); }}>
            <option value="">Myself ({user.email})</option>
            {users.filter((u) => u.id !== user.id).map((u) => <option key={u.id} value={u.id}>{u.email || u.name}</option>)}
          </select>
        </div>
      ) : null}
      <div className="nb-settings-grid">
        <section className="nb-card nb-stack-wide" aria-labelledby="hrmax-h">
          <h2 id="hrmax-h" className="nb-card-title">Max HR</h2>
          <p className="nb-muted nb-small">{data.sessionsReady} ready session{data.sessionsReady === 1 ? '' : 's'}.{' '}
            {data.method ? `Currently: ${LABEL[data.method]} · ${data.effective?.value ?? '—'} bpm.` : 'Not set: each session uses its upload override, else 210 − age at recording.'}</p>
          <fieldset className="nb-radios"><legend className="nb-sr">Method</legend>
            {data.options.map((o) => (
              <label key={o.method} className={`nb-radio-row${method === o.method ? ' is-on' : ''}`}>
                <input type="radio" name="hrmax" value={o.method} checked={method === o.method} onChange={() => setMethod(o.method)} />
                <span><b>{LABEL[o.method]}</b><span className="nb-muted nb-small"> — {o.detail}</span></span>
                <span className="nb-radio-val">{o.method === 'manual' ? (
                  <input className="nb-input nb-input-sm" type="number" min="100" max="230" aria-label="Manual max HR (bpm)" value={manual}
                    onChange={(e) => { setManual(e.target.value); setMethod('manual'); }} />
                ) : `${o.value ?? '—'} bpm`}</span>
              </label>
            ))}
          </fieldset>
          {fieldErr.manualValue || (method === 'manual' && manual && !manualOk) ? <div className="nb-field-error">{fieldErr.manualValue || 'Enter a max HR between 100 and 230 bpm'}</div> : null}
          {fieldErr.method ? <div className="nb-field-error">{fieldErr.method}</div> : null}
          <div className="nb-row">
            <span className="nb-muted nb-small" role="status">{changed ? 'Unsaved changes' : ''}</span>
            <Button variant="primary" onClick={save} disabled={!changed || !valid} busy={busy}>Save max HR</Button>
          </div>
          {msg ? <Alert tone={msg.tone}>{msg.text}</Alert> : null}
        </section>
        <section className="nb-card" aria-labelledby="zones-h">
          <h2 id="zones-h" className="nb-card-title">Zones at {preview ?? '—'} bpm</h2>
          {preview ? (
            <table className="nb-table nb-table-compact">
              <thead><tr><th>Zone</th><th>% HRmax</th><th>bpm</th></tr></thead>
              <tbody>{ROWS.map(([z, a, b, c]) => (
                <tr key={z}><td><b style={{ color: c }}>{z}</b></td><td>{a * 100}{b ? `–${b * 100}` : '+'} %</td>
                  <td>{Math.round(a * preview)}{b ? `–${Math.round(b * preview) - 1}` : '+'}</td></tr>))}</tbody>
            </table>
          ) : <p className="nb-muted">Choose a method with a value to preview zones.</p>}
        </section>
      </div>
    </>
  );
}
