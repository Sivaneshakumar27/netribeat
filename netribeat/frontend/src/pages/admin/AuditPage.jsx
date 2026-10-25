import { useCallback, useEffect, useState } from 'react';
import { adminApi } from '../../api/client.js';
import { Alert, Button } from '../../components/ui.jsx';
import { formatDateTime } from '../../utils/format.js';

const PAGE = 50;
const ACTIONS = [
  'auth.login', 'auth.login_failed', 'auth.logout', 'auth.registered', 'auth.register_existing',
  'auth.reset_requested', 'auth.password_reset', 'auth.refresh_reuse', 'user.password_changed',
  'user.profile_updated', 'user.session_revoked', 'user.other_sessions_revoked',
  'admin.user_created', 'admin.user_disabled', 'admin.user_enabled', 'admin.role_changed',
  'admin.sessions_revoked', 'cli.admin_provisioned', 'cli.user_created', 'cli.role_changed',
  'cli.user_disabled', 'cli.user_enabled',
];

const short = (id) => (id ? `${id.slice(0, 8)}…` : '—');

export default function AuditPage() {
  const [action, setAction] = useState('');
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState({ loading: true, items: [], total: 0, error: '' });

  const load = useCallback(async () => {
    setData((d) => ({ ...d, loading: true, error: '' }));
    try {
      const r = await adminApi.audit({ action, limit: PAGE, offset });
      setData({ loading: false, items: r.items, total: r.total, error: '' });
    } catch (e) {
      setData({ loading: false, items: [], total: 0, error: e.message });
    }
  }, [action, offset]);
  useEffect(() => { load(); }, [load]);

  return (
    <>
      <header className="nb-page-head">
        <div>
          <h1 className="nb-page-title">Audit log</h1>
          <p className="nb-muted">Security events, newest first. Ids only — no emails, passwords or codes are recorded.</p>
        </div>
        <Button onClick={load}>Refresh</Button>
      </header>
      <section className="nb-card nb-card-flush" aria-busy={data.loading || undefined}>
        <div className="nb-filters">
          <div className="nb-field">
            <label className="nb-field-label" htmlFor="a-action">Event</label>
            <select id="a-action" className="nb-input" value={action} onChange={(e) => { setAction(e.target.value); setOffset(0); }}>
              <option value="">All events</option>
              {ACTIONS.map((a) => <option key={a} value={a}>{a}</option>)}
            </select>
          </div>
        </div>
        <Alert>{data.error}</Alert>
        <div className="nb-table-wrap">
          <table className="nb-table">
            <thead><tr><th>Time</th><th>Event</th><th>Actor</th><th>Target</th><th>IP</th><th>Details</th></tr></thead>
            <tbody>
              {!data.loading && data.items.length === 0 ? <tr><td colSpan={6} className="nb-empty">No events.</td></tr> : null}
              {data.items.map((e) => (
                <tr key={e.id}>
                  <td>{formatDateTime(e.createdAt)}</td>
                  <td className="nb-mono">{e.action}</td>
                  <td className="nb-mono" title={e.actorUserId || ''}>{short(e.actorUserId)}</td>
                  <td className="nb-mono" title={e.targetUserId || ''}>{short(e.targetUserId)}</td>
                  <td className="nb-mono">{e.ipAddress || '—'}</td>
                  <td className="nb-mono nb-small">{Object.entries(e.details).filter(([k]) => !k.endsWith('_id')).map(([k, v]) => `${k}=${typeof v === 'object' ? JSON.stringify(v) : v}`).join(' ')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="nb-pager">
          <Button onClick={() => setOffset(Math.max(0, offset - PAGE))} disabled={offset === 0}>Newer</Button>
          <span className="nb-muted">{data.total} events</span>
          <Button onClick={() => setOffset(offset + PAGE)} disabled={offset + PAGE >= data.total}>Older</Button>
        </div>
      </section>
    </>
  );
}
