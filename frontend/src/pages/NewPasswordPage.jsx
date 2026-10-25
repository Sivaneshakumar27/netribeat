import { useState } from 'react';
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { ApiError, authApi } from '../api/client.js';
import { Alert, AuthLayout, Button, Field } from '../components/ui.jsx';
import { MIN_PASSWORD } from '../utils.js';

export default function NewPasswordPage() {
  const navigate = useNavigate();
  const { resetToken, email } = useLocation().state || {};
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [tried, setTried] = useState(false);
  const [serverFields, setServerFields] = useState({});
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  if (!resetToken) return <Navigate to="/forgot-password" replace />;

  const pwLocal = password.length < MIN_PASSWORD ? `Use at least ${MIN_PASSWORD} characters` : null;
  const cfLocal = !confirm ? 'Confirm your password' : confirm !== password ? "Passwords don't match" : null;

  async function submit() {
    setTried(true);
    setError('');
    setServerFields({});
    if (pwLocal || cfLocal) return;
    setBusy(true);
    try {
      await authApi.resetPassword({ resetToken, password, confirmPassword: confirm });
      navigate('/login', { replace: true, state: { email, notice: 'Password changed. All your devices were signed out — sign in with your new password.' } });
    } catch (e) {
      if (e instanceof ApiError && e.code === 'validation_error') setServerFields(e.fields);
      else setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthLayout title="Choose a new password" subtitle="This signs you out on every device." onSubmit={submit}>
      <Alert>{error}{error ? <> <Link className="nb-link" to="/forgot-password">Start again</Link></> : null}</Alert>
      <Field label="New password" type="password" autoComplete="new-password" value={password} onChange={setPassword} error={serverFields.password || (tried ? pwLocal : null)} hint={`At least ${MIN_PASSWORD} characters.`} required />
      <Field label="Confirm new password" type="password" autoComplete="new-password" value={confirm} onChange={setConfirm} error={serverFields.confirmPassword || (tried ? cfLocal : null)} required />
      <Button type="submit" variant="primary" block busy={busy}>Save new password</Button>
    </AuthLayout>
  );
}
