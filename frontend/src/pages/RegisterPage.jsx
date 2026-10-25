import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { ApiError, authApi } from '../api/client.js';
import { Alert, AuthLayout, Button, Field } from '../components/ui.jsx';
import { EMAIL_MSG, MIN_PASSWORD, isEmail, normEmail } from '../utils.js';

export default function RegisterPage() {
  const navigate = useNavigate();
  const [f, setF] = useState({ firstName: '', lastName: '', email: '', password: '', confirmPassword: '' });
  const [tried, setTried] = useState(false);
  const [serverFields, setServerFields] = useState({});
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const set = (k) => (v) => { setF((s) => ({ ...s, [k]: v })); setServerFields((s) => ({ ...s, [k]: undefined })); };

  const local = {
    firstName: !f.firstName.trim() ? 'Enter your first name' : null,
    lastName: !f.lastName.trim() ? 'Enter your last name' : null,
    email: !isEmail(f.email) ? EMAIL_MSG : null,
    password: f.password.length < MIN_PASSWORD ? `Use at least ${MIN_PASSWORD} characters` : null,
    confirmPassword: !f.confirmPassword ? 'Confirm your password' : f.confirmPassword !== f.password ? "Passwords don't match" : null,
  };
  const err = (k) => serverFields[k] || (tried ? local[k] : null);

  async function submit() {
    setTried(true);
    setError('');
    if (Object.values(local).some(Boolean)) return;
    setBusy(true);
    const email = normEmail(f.email);
    try {
      // `role` is not sent: the server always creates a `user` account.
      await authApi.register({ ...f, firstName: f.firstName.trim(), lastName: f.lastName.trim(), email });
      navigate('/verify-email', { state: { email, justRegistered: true } });
    } catch (e) {
      if (e instanceof ApiError && e.code === 'validation_error') setServerFields(e.fields);
      else setError(e.status === 429 ? 'Too many sign-ups from this network. Try again later.' : e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthLayout title="Create your account" subtitle="We'll email you a code to confirm your address." onSubmit={submit}>
      <Alert>{error}</Alert>
      <div className="nb-grid-2">
        <Field label="First name" autoComplete="given-name" value={f.firstName} onChange={set('firstName')} error={err('firstName')} required />
        <Field label="Last name" autoComplete="family-name" value={f.lastName} onChange={set('lastName')} error={err('lastName')} required />
      </div>
      <div className="nb-field">
        <span className="nb-field-label" id="role-label">Account type</span>
        <div className="nb-locked" aria-labelledby="role-label">User <small>Administrator accounts are created by your NetriBeat operator.</small></div>
      </div>
      <Field label="Email" type="email" autoComplete="email" inputMode="email" value={f.email} onChange={set('email')} error={err('email')} placeholder="name@institute.org" required />
      <Field label="Password" type="password" autoComplete="new-password" value={f.password} onChange={set('password')} error={err('password')} hint={`At least ${MIN_PASSWORD} characters. A short phrase works well.`} required />
      <Field label="Confirm password" type="password" autoComplete="new-password" value={f.confirmPassword} onChange={set('confirmPassword')} error={err('confirmPassword')} required />
      <Button type="submit" variant="primary" block busy={busy}>Create account</Button>
      <p className="nb-auth-foot">Already have an account? <Link className="nb-link" to="/login">Sign in</Link></p>
    </AuthLayout>
  );
}
