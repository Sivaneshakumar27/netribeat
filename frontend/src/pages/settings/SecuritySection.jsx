import { useCallback, useEffect, useState } from 'react';
import { ApiError, accountApi, authApi } from '../../api/client.js';
import { ConfirmModal } from '../../components/Modal.jsx';
import { Alert, Button, Field } from '../../components/ui.jsx';
import { MIN_PASSWORD } from '../../utils/validation.js';
import { describeAgent, formatDateTime } from '../../utils/format.js';

function Sessions() {
  const [state, setState] = useState({ loading: true, items: [], error: '' });
  const [confirm, setConfirm] = useState(null); // {kind:'one'|'others', session}
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');

  const load = useCallback(async () => {
    setState((s) => ({ ...s, loading: true, error: '' }));
    try {
      const r = await accountApi.sessions();
      setState({ loading: false, items: r.items, error: '' });
    } catch (e) {
      setState({ loading: false, items: [], error: e.message });
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  async function doConfirm() {
    setBusy(true);
    try {
      if (confirm.kind === 'one') await accountApi.revokeSession(confirm.session.id);
      else await accountApi.revokeOtherSessions();
      setNotice(confirm.kind === 'one' ? 'That device was signed out.' : 'All other devices were signed out.');
      setConfirm(null);
      await load();
    } catch (e) {
      setConfirm((c) => ({ ...c, error: e.message }));
    } finally {
      setBusy(false);
    }
  }

  const others = state.items.filter((s) => !s.current).length;
  return (
    <section className="nb-card" aria-labelledby="sess-h" aria-busy={state.loading || undefined}>
      <div className="nb-card-head">
        <h2 id="sess-h" className="nb-card-title">Signed-in devices</h2>
        <Button variant="ghost" onClick={() => setConfirm({ kind: 'others' })} disabled={others === 0}>Sign out all other devices</Button>
      </div>
      <Alert tone="success">{notice}</Alert>
      <Alert>{state.error}</Alert>
      {state.loading ? <div className="nb-loading-inline" role="status"><span className="nb-spinner" aria-hidden="true" /> Loading devices…</div> : (
        <ul className="nb-list">
          {state.items.map((s) => (
            <li key={s.id} className="nb-list-row">
              <div>
                <b>{describeAgent(s.userAgent)}</b>{s.current ? <span className="nb-badge nb-badge-ok">This device</span> : null}
                <div className="nb-muted nb-small">
                  {s.ipAddress || 'unknown IP'} · signed in {formatDateTime(s.createdAt)} · last active {formatDateTime(s.lastUsedAt)} · {s.remember ? 'kept signed in' : 'session only'} until {formatDateTime(s.expiresAt)}
                </div>
              </div>
              {!s.current ? <Button onClick={() => setConfirm({ kind: 'one', session: s })}>Sign out device</Button> : null}
            </li>
          ))}
        </ul>
      )}
      {confirm ? (
        <ConfirmModal
          title={confirm.kind === 'one' ? 'Sign out this device?' : 'Sign out all other devices?'}
          body={confirm.kind === 'one' ? `${describeAgent(confirm.session.userAgent)} (${confirm.session.ipAddress || 'unknown IP'}) will need to sign in again.` : 'Every device except this one will need to sign in again.'}
          confirmLabel="Sign out" danger busy={busy} error={confirm.error}
          onConfirm={doConfirm} onClose={() => setConfirm(null)}
        />
      ) : null}
    </section>
  );
}

function ChangePassword() {
  const empty = { currentPassword: '', newPassword: '', confirmPassword: '' };
  const [pw, setPw] = useState(empty);
  const [fields, setFields] = useState({});
  const [msg, setMsg] = useState({ tone: 'error', text: '' });
  const [busy, setBusy] = useState(false);
  const set = (k) => (v) => setPw((s) => ({ ...s, [k]: v }));

  async function submit(e) {
    e.preventDefault();
    setFields({});
    setMsg({ tone: 'error', text: '' });
    const local = {};
    if (!pw.currentPassword) local.currentPassword = 'Enter your current password';
    if (pw.newPassword.length < MIN_PASSWORD) local.newPassword = `Use at least ${MIN_PASSWORD} characters`;
    if (!pw.confirmPassword) local.confirmPassword = 'Confirm your new password';
    else if (pw.confirmPassword !== pw.newPassword) local.confirmPassword = "Passwords don't match";
    if (Object.keys(local).length) { setFields(local); return; }
    setBusy(true);
    try {
      await authApi.changePassword(pw);
      setPw(empty);
      setMsg({ tone: 'success', text: 'Password changed. Your other devices were signed out.' });
    } catch (err) {
      if (err instanceof ApiError && err.code === 'validation_error') setFields(err.fields);
      else setMsg({ tone: 'error', text: err.message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="nb-card" aria-labelledby="pw-h">
      <h2 id="pw-h" className="nb-card-title">Change password</h2>
      <form className="nb-stack" onSubmit={submit} noValidate>
        <Alert tone={msg.tone}>{msg.text}</Alert>
        <Field label="Current password" type="password" autoComplete="current-password" value={pw.currentPassword} onChange={set('currentPassword')} error={fields.currentPassword} />
        <Field label="New password" type="password" autoComplete="new-password" value={pw.newPassword} onChange={set('newPassword')} error={fields.newPassword} hint={`At least ${MIN_PASSWORD} characters.`} />
        <Field label="Confirm new password" type="password" autoComplete="new-password" value={pw.confirmPassword} onChange={set('confirmPassword')} error={fields.confirmPassword} />
        <div><Button type="submit" variant="primary" busy={busy}>Change password</Button></div>
      </form>
    </section>
  );
}

/** Password and signed-in devices. */
export default function SecuritySection() {
  return (
    <>
      <ChangePassword />
      <Sessions />
    </>
  );
}
