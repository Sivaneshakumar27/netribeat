import { useCallback, useEffect, useState } from 'react';
import { ApiError, adminApi } from '../../api/client.js';
import { useAuth } from '../../auth/AuthContext.jsx';
import Modal, { ConfirmModal } from '../../components/Modal.jsx';
import { Alert, Button, Field } from '../../components/ui.jsx';
import { EMAIL_MSG, isEmail, normEmail } from '../../utils.js';
import { formatDateTime } from '../../utils/format.js';

const PAGE = 20;

function useDebounced(value, ms) {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setV(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return v;
}

function CreateUserModal({ onClose, onCreated }) {
  const [f, setF] = useState({ firstName: '', lastName: '', email: '', sendInvite: true });
  const [fields, setFields] = useState({});
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const set = (k) => (v) => setF((s) => ({ ...s, [k]: v }));

  async function submit(e) {
    e.preventDefault();
    const local = {};
    if (!f.firstName.trim()) local.firstName = 'Enter a first name';
    if (!f.lastName.trim()) local.lastName = 'Enter a last name';
    if (!isEmail(f.email)) local.email = EMAIL_MSG;
    setFields(local);
    setError('');
    if (Object.keys(local).length) return;
    setBusy(true);
    try {
      const user = await adminApi.createUser({ ...f, email: normEmail(f.email), firstName: f.firstName.trim(), lastName: f.lastName.trim() });
      onCreated(user);
    } catch (err) {
      if (err instanceof ApiError && err.code === 'validation_error') setFields(err.fields);
      else if (err instanceof ApiError && err.status === 409) setFields({ email: 'A user with this email already exists' });
      else setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal title="Create user" onClose={onClose}>
      <form className="nb-stack" onSubmit={submit} noValidate>
        <p className="nb-muted nb-small">The account is created without a password and with role <b>user</b>. The person sets their own password with "Forgot password?", which also verifies their email.</p>
        <Alert>{error}</Alert>
        <div className="nb-grid-2">
          <Field label="First name" value={f.firstName} onChange={set('firstName')} error={fields.firstName} />
          <Field label="Last name" value={f.lastName} onChange={set('lastName')} error={fields.lastName} />
        </div>
        <Field label="Email" type="email" value={f.email} onChange={set('email')} error={fields.email} />
        <label className="nb-check"><input type="checkbox" checked={f.sendInvite} onChange={(e) => set('sendInvite')(e.target.checked)} />Email them instructions</label>
        <div className="nb-modal-actions">
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="primary" busy={busy}>Create user</Button>
        </div>
      </form>
    </Modal>
  );
}

const ACTIONS = {
  disable: { title: 'Disable account?', label: 'Disable', danger: true, body: (u) => `${u.email} will be signed out everywhere and won't be able to sign in until re-enabled.`, run: (u) => adminApi.setActive(u.id, false) },
  enable: { title: 'Enable account?', label: 'Enable', body: (u) => `${u.email} will be able to sign in again.`, run: (u) => adminApi.setActive(u.id, true) },
  promote: { title: 'Make administrator?', label: 'Make admin', danger: true, body: (u) => `${u.email} will be able to manage every user. They'll be signed out and must sign in again.`, run: (u) => adminApi.setRole(u.id, 'admin') },
  demote: { title: 'Remove administrator role?', label: 'Make user', danger: true, body: (u) => `${u.email} will lose admin access and be signed out.`, run: (u) => adminApi.setRole(u.id, 'user') },
  signout: { title: 'Sign out everywhere?', label: 'Sign out', danger: true, body: (u) => `Every device signed in as ${u.email} will be signed out.`, run: (u) => adminApi.revokeSessions(u.id) },
};

export default function UsersPage() {
  const { user: me } = useAuth();
  const [q, setQ] = useState('');
  const [role, setRole] = useState('');
  const [status, setStatus] = useState('');
  const [sort, setSort] = useState('-createdAt');
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState({ loading: true, items: [], total: 0, error: '' });
  const [creating, setCreating] = useState(false);
  const [pending, setPending] = useState(null); // {action, user, error}
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');
  const dq = useDebounced(q, 300);

  const load = useCallback(async () => {
    setData((d) => ({ ...d, loading: true, error: '' }));
    try {
      const r = await adminApi.listUsers({ q: dq, role, isActive: status, sort, limit: PAGE, offset });
      setData({ loading: false, items: r.items, total: r.total, error: '' });
    } catch (e) {
      setData({ loading: false, items: [], total: 0, error: e.message });
    }
  }, [dq, role, status, sort, offset]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { setOffset(0); }, [dq, role, status, sort]);

  async function runAction() {
    const a = ACTIONS[pending.action];
    setBusy(true);
    try {
      await a.run(pending.user);
      setNotice(`${a.label}: done for ${pending.user.email}.`);
      setPending(null);
      await load();
    } catch (e) {
      setPending((p) => ({ ...p, error: e.message }));
    } finally {
      setBusy(false);
    }
  }

  const pages = Math.max(1, Math.ceil(data.total / PAGE));
  const page = Math.floor(offset / PAGE) + 1;

  return (
    <>
      <header className="nb-page-head">
        <div>
          <h1 className="nb-page-title">Users</h1>
          <p className="nb-muted">{data.loading ? 'Loading…' : `${data.total} account${data.total === 1 ? '' : 's'}`}</p>
        </div>
        <Button variant="primary" onClick={() => setCreating(true)}>Create user</Button>
      </header>
      <Alert tone="success">{notice}</Alert>
      <section className="nb-card nb-card-flush" aria-label="Users" aria-busy={data.loading || undefined}>
        <div className="nb-filters">
          <div className="nb-field nb-grow">
            <label className="nb-field-label" htmlFor="u-q">Search</label>
            <input id="u-q" className="nb-input" type="search" placeholder="Name or email" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          <div className="nb-field">
            <label className="nb-field-label" htmlFor="u-role">Role</label>
            <select id="u-role" className="nb-input" value={role} onChange={(e) => setRole(e.target.value)}>
              <option value="">All</option><option value="user">User</option><option value="admin">Admin</option>
            </select>
          </div>
          <div className="nb-field">
            <label className="nb-field-label" htmlFor="u-status">Status</label>
            <select id="u-status" className="nb-input" value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">All</option><option value="true">Active</option><option value="false">Disabled</option>
            </select>
          </div>
          <div className="nb-field">
            <label className="nb-field-label" htmlFor="u-sort">Sort</label>
            <select id="u-sort" className="nb-input" value={sort} onChange={(e) => setSort(e.target.value)}>
              <option value="-createdAt">Newest</option><option value="createdAt">Oldest</option>
              <option value="email">Email A–Z</option><option value="name">Last name</option>
              <option value="-lastLoginAt">Last sign-in</option>
            </select>
          </div>
        </div>
        <Alert>{data.error}</Alert>
        <div className="nb-table-wrap">
          <table className="nb-table">
            <thead>
              <tr><th>Name</th><th>Email</th><th>Role</th><th>Status</th><th>Last sign-in</th><th><span className="nb-sr">Actions</span></th></tr>
            </thead>
            <tbody>
              {!data.loading && data.items.length === 0 ? (
                <tr><td colSpan={6} className="nb-empty">No users match these filters.</td></tr>
              ) : null}
              {data.items.map((u) => {
                const self = u.id === me.id;
                return (
                  <tr key={u.id}>
                    <td>{u.name}{self ? <span className="nb-badge nb-badge-ok">You</span> : null}</td>
                    <td className="nb-mono">{u.email || '—'}</td>
                    <td><span className={`nb-badge ${u.role === 'admin' ? 'nb-badge-admin' : ''}`}>{u.role}</span></td>
                    <td>
                      <span className={`nb-badge ${u.isActive ? 'nb-badge-ok' : 'nb-badge-off'}`}>{u.isActive ? 'active' : 'disabled'}</span>
                      {!u.hasPassword ? <span className="nb-badge" title="Hasn't set a password yet">invited</span> : null}
                    </td>
                    <td>{formatDateTime(u.lastLoginAt)}</td>
                    <td className="nb-actions">
                      {self ? <span className="nb-muted nb-small">—</span> : (
                        <>
                          <Button variant="ghost" onClick={() => setPending({ action: u.isActive ? 'disable' : 'enable', user: u })}>{u.isActive ? 'Disable' : 'Enable'}</Button>
                          <Button variant="ghost" onClick={() => setPending({ action: u.role === 'admin' ? 'demote' : 'promote', user: u })}>{u.role === 'admin' ? 'Make user' : 'Make admin'}</Button>
                          <Button variant="ghost" onClick={() => setPending({ action: 'signout', user: u })}>Sign out</Button>
                        </>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <div className="nb-pager">
          <Button onClick={() => setOffset(Math.max(0, offset - PAGE))} disabled={offset === 0}>Previous</Button>
          <span className="nb-muted">Page {page} of {pages}</span>
          <Button onClick={() => setOffset(offset + PAGE)} disabled={offset + PAGE >= data.total}>Next</Button>
        </div>
      </section>
      {creating ? (
        <CreateUserModal onClose={() => setCreating(false)} onCreated={(u) => { setCreating(false); setNotice(`Created ${u.email}.`); load(); }} />
      ) : null}
      {pending ? (
        <ConfirmModal
          title={ACTIONS[pending.action].title}
          body={ACTIONS[pending.action].body(pending.user)}
          confirmLabel={ACTIONS[pending.action].label}
          danger={ACTIONS[pending.action].danger}
          busy={busy} error={pending.error}
          onConfirm={runAction} onClose={() => setPending(null)}
        />
      ) : null}
    </>
  );
}
