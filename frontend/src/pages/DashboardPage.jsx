import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { sessionsApi } from '../api/client.js';
import { useAuth } from '../auth/AuthContext.jsx';
import BarChart from '../charts/BarChart.jsx';
import LineChart from '../charts/LineChart.jsx';
import { MetricTile, QualityBadge, StatusBadge, TypePill } from '../components/badges.jsx';
import { Alert } from '../components/ui.jsx';
import { formatDateTime } from '../utils/format.js';
import { TYPE_COLOR, duration, num } from '../utils/session.js';

export default function DashboardPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [state, setState] = useState({ loading: true, items: [], error: '' });

  useEffect(() => {
    let alive = true;
    sessionsApi.list({ limit: 200 })
      .then((r) => alive && setState({ loading: false, items: r.items, error: '' }))
      .catch((e) => alive && setState({ loading: false, items: [], error: e.message }));
    return () => { alive = false; };
  }, []);

  const ready = state.items.filter((s) => s.status === 'ready');
  const latest = ready[0];
  const chrono = [...ready].reverse();
  const rmssds = ready.map((s) => s.rmssd).filter((v) => v !== null);
  const mean = rmssds.length ? rmssds.reduce((a, b) => a + b, 0) / rmssds.length : null;
  const sd = rmssds.length > 1 ? Math.sqrt(rmssds.reduce((a, b) => a + (b - mean) ** 2, 0) / (rmssds.length - 1)) : null;
  const z = latest?.rmssd !== null && latest?.rmssd !== undefined && sd ? (latest.rmssd - mean) / sd : null;
  const withRmssd = chrono.filter((s) => s.rmssd !== null);

  return (
    <>
      <header className="nb-page-head">
        <div>
          <h1 className="nb-page-title">Good to see you, {user.firstName || user.email.split('@')[0]}</h1>
          <p className="nb-muted">{user.role === 'admin' ? 'All users\u2019 sessions are visible to you as an administrator.' : 'Your latest sessions and trends.'}</p>
        </div>
        <Link className="nb-btn nb-btn-primary" to="/upload">+ New recording</Link>
      </header>
      <Alert>{state.error}</Alert>
      {state.loading ? <div className="nb-loading-inline" role="status"><span className="nb-spinner" aria-hidden="true" /> Loading sessions…</div> : null}
      {!state.loading && !state.items.length ? (
        <section className="nb-card nb-empty-card">
          <h2 className="nb-card-title">No recordings yet</h2>
          <p className="nb-muted">Upload a Synapse sensor hex file (<b>.txt</b>) to see heart rate, HRV, training load and movement load.</p>
          <Link className="nb-btn nb-btn-primary" to="/upload">Upload a recording</Link>
        </section>
      ) : null}
      {latest ? (
        <>
          <div className="nb-tiles nb-tiles-4">
            <MetricTile label="Avg HR · latest" value={num(latest.avgHr, 0)} unit="bpm" sub={`max ${num(latest.maxHr, 0)} bpm · ${latest.type}`} />
            <MetricTile label="RMSSD · latest" value={num(latest.rmssd, 1)} unit="ms"
              sub={z !== null ? `${z >= 0 ? '+' : ''}${z.toFixed(1)} SD vs your mean` : 'needs ≥ 2 sessions with HRV'} />
            <MetricTile label="Training load · latest" value={num(latest.trainingLoad, 0)} unit="AU" sub="Banister TRIMP" />
            <div className="nb-tile"><div className="nb-tile-label">Signal quality · latest</div>
              <div className="nb-tile-value nb-tile-badge"><QualityBadge quality={latest.quality} reliable={latest.reliable} /></div>
              <div className="nb-tile-sub">{formatDateTime(latest.recordedAt)}</div></div>
          </div>
          {chrono.length >= 2 ? (
            <div className="nb-grid-2 nb-grid-gap">
              <section className="nb-card"><h2 className="nb-card-title">RMSSD by session</h2>
                {withRmssd.length >= 2 ? (
                  <LineChart title="RMSSD by session" height={200}
                    series={[{ name: 'RMSSD', unit: 'ms', color: 'var(--band-hf)', xs: withRmssd.map((_, i) => i + 1), ys: withRmssd.map((s) => s.rmssd) }]}
                    bands={mean !== null && sd ? [] : []}
                    xFormat={(v) => `#${Math.round(v)}`} yFormat={(v) => Math.round(v)} xLabel="Session" />
                ) : <p className="nb-muted">Needs at least two sessions with HRV.</p>}
                {mean !== null ? <p className="nb-muted nb-small">Mean {mean.toFixed(1)} ms{sd ? ` · SD ${sd.toFixed(1)} ms` : ''}</p> : null}
              </section>
              <section className="nb-card"><h2 className="nb-card-title">Training load by session</h2>
                <BarChart title="Training load by session" unit="AU"
                  items={chrono.map((s, i) => ({ label: `#${i + 1}`, value: s.trainingLoad, color: TYPE_COLOR[s.type], sub: `${s.type} · ${formatDateTime(s.recordedAt)}` }))} />
              </section>
            </div>
          ) : null}
        </>
      ) : null}
      {state.items.length ? (
        <section className="nb-card nb-card-flush">
          <div className="nb-card-head nb-pad"><h2 className="nb-card-title">Recent sessions</h2><Link className="nb-link" to="/sessions">All sessions →</Link></div>
          <div className="nb-table-wrap">
            <table className="nb-table">
              <thead><tr><th>Session</th>{user.role === 'admin' ? <th>User</th> : null}<th>Duration</th><th>Avg HR</th><th>RMSSD</th><th>Quality</th><th>Status</th></tr></thead>
              <tbody>
                {state.items.slice(0, 6).map((s) => (
                  <tr key={s.id} className="nb-row-link" tabIndex={0} onClick={() => navigate(`/sessions/${s.id}`)} onKeyDown={(e) => { if (e.key === 'Enter') navigate(`/sessions/${s.id}`); }}>
                    <td><TypePill type={s.type} /><div className="nb-muted nb-small">{formatDateTime(s.recordedAt)}</div></td>
                    {user.role === 'admin' ? <td className="nb-mono">{s.userEmail || s.userName}</td> : null}
                    <td>{duration(s.durationS)}</td><td>{num(s.avgHr, 0, 'bpm')}</td><td>{num(s.rmssd, 1, 'ms')}</td>
                    <td><QualityBadge quality={s.quality} reliable={s.reliable} /></td><td><StatusBadge status={s.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ) : null}
    </>
  );
}
