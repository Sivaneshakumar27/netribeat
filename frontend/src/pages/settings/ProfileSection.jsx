import { useState } from 'react';
import { ApiError, accountApi } from '../../api/client.js';
import { useAuth } from '../../auth/AuthContext.jsx';
import { Alert, Button, Field } from '../../components/ui.jsx';
import { formatDateTime } from '../../utils/format.js';

/** Your account: name (editable), email, role and sign-in dates. Athlete details are entered per upload. */
export default function ProfileSection() {
  const { user, setUser } = useAuth();
  const [editing, setEditing] = useState(false);
  const init = () => ({ firstName: user.firstName || '', lastName: user.lastName || '' });
  const [form, setForm] = useState(init);
  const [fields, setFields] = useState({});
  const [msg, setMsg] = useState(null);
  const [busy, setBusy] = useState(false);

  async function save(e) {
    e.preventDefault();
    const local = {};
    if (!form.firstName.trim()) local.firstName = 'Enter your first name';
    if (!form.lastName.trim()) local.lastName = 'Enter your last name';
    setFields(local);
    if (Object.keys(local).length) return;
    setBusy(true);
    try {
      setUser(await accountApi.updateProfile({ firstName: form.firstName.trim(), lastName: form.lastName.trim() }));
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
    <section className="nb-card" aria-labelledby="profile-h">
      <div className="nb-card-head">
        <h2 id="profile-h" className="nb-card-title">Profile</h2>
        {!editing ? <Button variant="ghost" onClick={() => { setEditing(true); setMsg(null); }}>Edit name</Button> : null}
      </div>
      {msg ? <Alert tone={msg.tone}>{msg.text}</Alert> : null}
      {editing ? (
        <form className="nb-stack" onSubmit={save} noValidate>
          <div className="nb-grid-2">
            <Field label="First name" autoComplete="given-name" value={form.firstName} onChange={(v) => setForm((s) => ({ ...s, firstName: v }))} error={fields.firstName} />
            <Field label="Last name" autoComplete="family-name" value={form.lastName} onChange={(v) => setForm((s) => ({ ...s, lastName: v }))} error={fields.lastName} />
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
          <dt>Member since</dt><dd>{formatDateTime(user.createdAt)}</dd>
          <dt>Last sign-in</dt><dd>{formatDateTime(user.lastLoginAt)}</dd>
        </dl>
      )}
      <p className="nb-muted nb-small">Athlete details (name, age, gender, resting HR, height, weight, max HR) are entered for each recording on the upload page.</p>
    </section>
  );
}
