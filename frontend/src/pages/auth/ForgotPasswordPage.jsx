import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { authApi } from '../../api/client.js';
import { Alert, AuthLayout, Button, Field } from '../../components/ui.jsx';
import { EMAIL_MSG, isEmail, normEmail } from '../../utils/validation.js';

export default function ForgotPasswordPage() {
  const navigate = useNavigate();
  const [email, setEmail] = useState('');
  const [tried, setTried] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function submit() {
    setTried(true);
    setError('');
    if (!isEmail(email)) return;
    setBusy(true);
    try {
      await authApi.forgotPassword(normEmail(email));
      navigate('/reset/verify', { state: { email: normEmail(email) } });
    } catch (e) {
      setError(e.status === 429 ? 'Too many requests from this network. Try again in an hour.' : e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthLayout title="Reset your password" subtitle="We'll email you a one-time code. Accounts created by an administrator use this to set their first password." onSubmit={submit}>
      <Alert>{error}</Alert>
      <Field label="Email" type="email" autoComplete="email" inputMode="email" value={email} onChange={setEmail} error={tried && !isEmail(email) ? EMAIL_MSG : null} placeholder="name@institute.org" required />
      <Button type="submit" variant="primary" block busy={busy}>Send reset code</Button>
      <p className="nb-auth-foot"><Link className="nb-link" to="/login">Back to sign in</Link></p>
    </AuthLayout>
  );
}
