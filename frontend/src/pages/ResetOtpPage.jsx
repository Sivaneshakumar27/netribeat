import { useState } from 'react';
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom';
import { authApi } from '../api/client.js';
import { Alert, AuthLayout, Button, Field, useCooldown } from '../components/ui.jsx';

export default function ResetOtpPage() {
  const navigate = useNavigate();
  const email = useLocation().state?.email;
  const [code, setCode] = useState('');
  const [tried, setTried] = useState(false);
  const [error, setError] = useState('');
  const [info, setInfo] = useState('If an account exists for this email, we sent a 6-digit code. It expires in 10 minutes.');
  const [busy, setBusy] = useState(false);
  const [cooldown, startCooldown] = useCooldown();
  if (!email) return <Navigate to="/forgot-password" replace />;
  const codeErr = tried && !/^\d{6}$/.test(code) ? 'Enter the 6-digit code from the email' : null;

  async function submit() {
    setTried(true);
    setError('');
    if (!/^\d{6}$/.test(code)) return;
    setBusy(true);
    try {
      const r = await authApi.verifyResetOtp({ email, code });
      // The reset token stays in memory (router state) only; it is never stored.
      navigate('/reset/new', { replace: true, state: { resetToken: r.resetToken, email } });
    } catch (e) {
      setError(e.status === 429 ? 'Too many attempts. Please wait and try again.' : e.message);
    } finally {
      setBusy(false);
    }
  }

  async function resend() {
    setError('');
    try {
      await authApi.forgotPassword(email);
      setInfo('If an account exists for this email, we sent a new code.');
      startCooldown(60);
    } catch (e) {
      setError(e.message);
    }
  }

  return (
    <AuthLayout title="Enter your reset code" subtitle={<>Sent to <b>{email}</b></>} onSubmit={submit}>
      <Alert tone="info">{info}</Alert>
      <Alert>{error}</Alert>
      <Field label="Reset code" inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code} onChange={(v) => setCode(v.replace(/\D/g, ''))} error={codeErr} className="nb-input nb-otp" required />
      <Button type="submit" variant="primary" block busy={busy}>Continue</Button>
      <div className="nb-row">
        <Button variant="ghost" onClick={resend} disabled={cooldown > 0}>{cooldown > 0 ? `Resend code in ${cooldown}s` : 'Resend code'}</Button>
        <Link className="nb-link" to="/forgot-password">Use a different email</Link>
      </div>
    </AuthLayout>
  );
}
