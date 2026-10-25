import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { sessionsApi } from '../api/client.js';
import { useAuth } from '../auth/AuthContext.jsx';
import { MetricTile, QualityBadge, StatusBadge, TypePill } from '../components/badges.jsx';
import { Alert, Button } from '../components/ui.jsx';
import { formatDateTime } from '../utils/format.js';
import { duration, num } from '../utils/session.js';

const PAGE = 50;

export default function SessionsPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [q, setQ] = useState('');
  const [dq, setDq] = useState('');
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState({ loading: true, items: [], total: 0, stats: null, error: '' });

  useEffect(() => { const t = setTimeout(() => { setDq(q); setOffset(0); }, 300); return () => clearTimeout(t); }, [q]);
  const load = useCallback(async () => {
    try {
      const r = await sessionsApi.list({ q: dq, limit: PAGE, offset });
      setData({ loading: false, items: r.items, total: r.total, stats: r.stats, error: '' });
    } catch (e) {
      setData((d) => ({ ...d, loading: false, error: e.message }));
    }
  }, [dq, offset]);
  useEffect(() => { load(); }, [load]);
  // Poll while anything is still being analysed.
  const busy = data.items.some((s) => s.status === 'processing');
  useEffect(() => { if (!busy) return undefined; const t = setInterval(load, 3000); return () => clearInterval(t); }, [busy, load]);

  const st = data.stats;
  return (
    <>
      <header className="nb-page-head"><div><h1 className="nb-page-title">Sessions</h1>
        <p className="nb-muted">{user.role === 'admin' ? 'Every user\u2019s recordings.' : 'Your recordings.'}</p></div>
        <Link className="nb-btn nb-btn-primary" to="/upload">+ New recording</Link></header>
      {st ? (
        <div className="nb-tiles nb-tiles-4">
          <MetricTile label="Sessions" value={st.sessions} />
          <MetricTile label={user.role === 'admin' ? 'Users' : 'Owner'} value={user.role === 'admin' ? st.users : 'You'} />
          <MetricTile label="Recorded time" value={duration(st.recordedTimeS)} />
          <MetricTile label="Avg RMSSD" value={num(st.avgRmssd, 1)} unit="ms" />
        </div>
      ) : null}
      <section className="nb-card nb-card-flush" aria-busy={data.loading || undefined}>
        <div className="nb-filters">
          <div className="nb-field nb-grow">
            <label className="nb-field-label" htmlFor="s-q">Search</label>
            <input id="s-q" className="nb-input" type="search" placeholder={user.role === 'admin' ? 'User email, name, file or type' : 'File name, type or notes'} value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
        </div>
        <Alert>{data.error}</Alert>
        <div className="nb-table-wrap">
          <table className="nb-table">
            <thead><tr><th>Session</th>{user.role === 'admin' ? <th>User</th> : null}<th>File</th><th>Duration</th><th>Avg HR</th><th>Max HR</th><th>RMSSD</th><th>Training load</th><th>Quality</th><th>Status</th></tr></thead>
            <tbody>
              {!data.loading && !data.items.length ? <tr><td colSpan={10} className="nb-empty">No sessions{dq ? ' match this search' : ' yet'}.</td></tr> : null}
              {data.items.map((s) => (
                <tr key={s.id} className="nb-row-link" tabIndex={0} onClick={() => navigate(`/sessions/${s.id}`)} onKeyDown={(e) => { if (e.key === 'Enter') navigate(`/sessions/${s.id}`); }}>
                  <td><TypePill type={s.type} /><div className="nb-muted nb-small">{formatDateTime(s.recordedAt)}</div></td>
                  {user.role === 'admin' ? <td className="nb-mono">{s.userEmail || s.userName}</td> : null}
                  <td className="nb-mono nb-small">{s.fileName}</td>
                  <td>{duration(s.durationS)}</td><td>{num(s.avgHr, 0)}</td><td>{num(s.maxHr, 0)}</td>
                  <td>{s.rmssd === null ? <span className="nb-muted">N/A</span> : num(s.rmssd, 1)}</td>
                  <td>{s.trainingLoad === null ? <span className="nb-muted">—</span> : (
                    <span className="nb-minibar"><span style={{ width: `${Math.min(100, (s.trainingLoad / 300) * 100)}%` }} />{num(s.trainingLoad, 0)}</span>)}</td>
                  <td><QualityBadge quality={s.quality} reliable={s.reliable} /></td>
                  <td><StatusBadge status={s.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="nb-pager">
          <Button onClick={() => setOffset(Math.max(0, offset - PAGE))} disabled={offset === 0}>Previous</Button>
          <span className="nb-muted">{data.total} session{data.total === 1 ? '' : 's'}</span>
          <Button onClick={() => setOffset(offset + PAGE)} disabled={offset + PAGE >= data.total}>Next</Button>
        </div>
      </section>
    </>
  );
}
