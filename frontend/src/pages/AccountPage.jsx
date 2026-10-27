import { useState } from 'react';
import { Link } from 'react-router-dom';
import { ApiError, accountApi } from '../api/client.js';
import { useAuth } from '../auth/AuthContext.jsx';
import { Alert, Button, Field } from '../components/ui.jsx';
import { formatDateTime } from '../utils/format.js';

export default function AccountPage() {
  const { user, setUser } = useAuth();
  const [editing, setEditing] = useState(false);
  const init = () => ({ firstName: user.firstName || '', lastName: user.lastName || '', age: user.age ?? '', gender: user.gender || '', heightCm: user.heightCm ?? '', weightKg: user.weightKg ?? '', hrRest: user.hrRest ?? '' });
  const [form, setForm] = useState(init);
  const [fields, setFields] = useState({});
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);

  async function save(e) {
    e.preventDefault();
    setFields({});
    const local = {};
    if (!form.firstName.trim()) local.firstName = 'Enter your first name';
    if (!form.lastName.trim()) local.lastName = 'Enter your last name';
    if (Object.keys(local).length) { setFields(local); return; }
    setBusy(true);
    try {
      const numOrNull = (v) => (v === '' || v === null ? null : Number(v));
      const updated = await accountApi.updateProfile({
        firstName: form.firstName.trim(), lastName: form.lastName.trim(), age: numOrNull(form.age),
        gender: form.gender || null, heightCm: numOrNull(form.heightCm), weightKg: numOrNull(form.weightKg), hrRest: numOrNull(form.hrRest),
      });
      setUser(updated);
      setEditing(false);
      setMsg({ tone: 'success', text: 'Profile saved.' });
    } catch (err) {
      if (err instanceof ApiError && err.code === 'validation_error') setFields(err.fields);
      else setMsg({ tone: 'error', text: err.message });
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <header className="nb-page-head">
        <div>
          <h1 className="nb-page-title">Account</h1>
          <p className="nb-muted">You're signed in{user.role === 'admin' ? ' as an administrator' : ''}.</p>
        </div>
        <span className={`nb-badge ${user.role === 'admin' ? 'nb-badge-admin' : ''}`}>{user.role}</span>
      </header>
      {msg ? <Alert tone={msg.tone}>{msg.text}</Alert> : null}
      <section className="nb-card" aria-labelledby="acct-h">
        <div className="nb-card-head">
          <h2 id="acct-h" className="nb-card-title">Account</h2>
          {!editing ? <Button variant="ghost" onClick={() => { setEditing(true); setMsg(null); }}>Edit profile</Button> : null}
        </div>
        {editing ? (
          <form className="nb-stack" onSubmit={save} noValidate>
            <div className="nb-grid-2">
              <Field label="First name" autoComplete="given-name" value={form.firstName} onChange={(v) => setForm((s) => ({ ...s, firstName: v }))} error={fields.firstName} />
              <Field label="Last name" autoComplete="family-name" value={form.lastName} onChange={(v) => setForm((s) => ({ ...s, lastName: v }))} error={fields.lastName} />
            </div>
            <p className="nb-muted nb-small">Optional subject details, shown in the HRV report header.</p>
            <div className="nb-grid-2">
              <Field label="Age (years)" type="number" value={String(form.age)} onChange={(v) => setForm((s) => ({ ...s, age: v }))} error={fields.age} min="8" max="100" />
              <div className="nb-field"><label className="nb-field-label" htmlFor="acct-gender">Gender</label>
                <select id="acct-gender" className="nb-input" value={form.gender} onChange={(e) => setForm((s) => ({ ...s, gender: e.target.value }))}>
                  <option value="">Not set</option><option value="female">Female</option><option value="male">Male</option><option value="other">Other</option>
                </select>{fields.gender ? <div className="nb-field-error">{fields.gender}</div> : null}</div>
              <Field label="Height (cm)" type="number" value={String(form.heightCm)} onChange={(v) => setForm((s) => ({ ...s, heightCm: v }))} error={fields.heightCm} min="80" max="250" />
              <Field label="Weight (kg)" type="number" value={String(form.weightKg)} onChange={(v) => setForm((s) => ({ ...s, weightKg: v }))} error={fields.weightKg} min="20" max="300" />
              <Field label="Resting HR (bpm)" type="number" value={String(form.hrRest)} onChange={(v) => setForm((s) => ({ ...s, hrRest: v }))} error={fields.hrRest} min="25" max="120" />
            </div>
            <div className="nb-row-start">
              <Button type="submit" variant="primary" busy={busy}>Save</Button>
              <Button onClick={() => { setEditing(false); setFields({}); setForm(init()); }}>Cancel</Button>
            </div>
          </form>
        ) : (
          <dl className="nb-dl">
            <dt>Name</dt><dd>{user.name}</dd>
            <dt>Email</dt><dd>{user.email}</dd>
            <dt>Role</dt><dd>{user.role}</dd>
            <dt>Email verified</dt><dd>{user.emailVerified ? 'Yes' : 'No'}</dd>
            <dt>Age · gender</dt><dd>{user.age ?? '—'} · {user.gender || '—'}</dd>
            <dt>Height · weight</dt><dd>{user.heightCm ? `${user.heightCm} cm` : '—'} · {user.weightKg ? `${user.weightKg} kg` : '—'}{user.heightCm && user.weightKg ? ` (BMI ${(user.weightKg / (user.heightCm / 100) ** 2).toFixed(1)})` : ''}</dd>
            <dt>Resting HR</dt><dd>{user.hrRest ? `${user.hrRest} bpm` : '—'}</dd>
            <dt>Member since</dt><dd>{formatDateTime(user.createdAt)}</dd>
            <dt>Last sign-in</dt><dd>{formatDateTime(user.lastLoginAt)}</dd>
          </dl>
        )}
      </section>
      <section className="nb-card">
        <h2 className="nb-card-title">Security</h2>
        <p className="nb-muted">Change your password and see which devices are signed in. <Link className="nb-link" to="/security">Open security settings</Link></p>
      </section>
    </>
  );
}
