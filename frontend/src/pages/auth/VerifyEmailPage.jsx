import { useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { ApiError, authApi } from '../../api/client.js';
import { Alert, AuthLayout, Button, Field, useCooldown } from '../../components/ui.jsx';
import { EMAIL_MSG, isEmail, normEmail } from '../../utils/validation.js';

export default function VerifyEmailPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState(location.state?.email || '');
  const [code, setCode] = useState('');
  const [tried, setTried] = useState(false);
  const [error, setError] = useState('');
  const [info, setInfo] = useState(location.state?.justRegistered ? 'If this email can be registered, we sent a 6-digit code to it. It expires in 10 minutes.' : '');
  const [busy, setBusy] = useState(false);
  const [cooldown, startCooldown] = useCooldown();

  const codeErr = tried && !/^\d{6}$/.test(code) ? 'Enter the 6-digit code from the email' : null;
  const emailErr = tried && !isEmail(email) ? EMAIL_MSG : null;

  async function submit() {
    setTried(true);
    setError('');
    if (codeErr || !isEmail(email) || !/^\d{6}$/.test(code)) return;
    setBusy(true);
    try {
      await authApi.verifyEmail({ email: normEmail(email), code });
      navigate('/login', { replace: true, state: { email: normEmail(email), notice: 'Your account is active. Sign in to continue.' } });
    } catch (e) {
      setError(e instanceof ApiError && e.status === 429 ? 'Too many attempts. Please wait and try again.' : e.message);
    } finally {
      setBusy(false);
    }
  }

  async function resend() {
    setError('');
    if (!isEmail(email)) { setTried(true); return; }
    try {
      const r = await authApi.resendVerification(normEmail(email));
      setInfo(r.message);
      startCooldown(60);
    } catch (e) {
      setError(e.message);
    }
  }

  return (
    <AuthLayout title="Check your email" subtitle="Enter the code we sent to activate your account." onSubmit={submit}>
      <Alert tone="info">{info}</Alert>
      <Alert>{error}</Alert>
      <Field label="Email" type="email" autoComplete="email" value={email} onChange={setEmail} error={emailErr} required />
      <Field label="Verification code" inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code} onChange={(v) => setCode(v.replace(/\D/g, ''))} error={codeErr} className="nb-input nb-otp" required />
      <Button type="submit" variant="primary" block busy={busy}>Verify and activate</Button>
      <div className="nb-row">
        <Button variant="ghost" onClick={resend} disabled={cooldown > 0}>{cooldown > 0 ? `Resend code in ${cooldown}s` : 'Resend code'}</Button>
        <Link className="nb-link" to="/register">Use a different email</Link>
      </div>
    </AuthLayout>
  );
}
