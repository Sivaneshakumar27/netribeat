import { useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { ApiError } from '../api/client.js';
import { useAuth } from '../auth/AuthContext.jsx';
import { Alert, AuthLayout, Button, Field } from '../components/ui.jsx';
import { EMAIL_MSG, isEmail, normEmail } from '../utils.js';

export default function LoginPage({ mode = 'user' }) {
  const admin = mode === 'admin';
  const { signIn } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState(location.state?.email || '');
  const [password, setPassword] = useState('');
  const [remember, setRemember] = useState(false);
  const [tried, setTried] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const notice = location.state?.notice;

  const emailErr = tried && !isEmail(email) ? EMAIL_MSG : null;
  const pwErr = tried && !password ? 'Enter your password' : null;

  async function submit() {
    setTried(true);
    setError('');
    if (!isEmail(email) || !password) return;
    setBusy(true);
    try {
      await signIn({ email: normEmail(email), password, remember, mode });
      navigate(admin ? '/admin' : '/', { replace: true });
    } catch (err) {
      if (err instanceof ApiError && err.status === 429) {
        setError('Too many attempts. Please wait 15 minutes and try again.');
      } else if (err instanceof ApiError && err.status === 401) {
        setError(admin ? 'Email or password is incorrect, or this account is not an administrator.' : 'Email or password is incorrect.');
      } else {
        setError(err.message);
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthLayout
      title={admin ? 'Administrator sign in' : 'Sign in'}
      subtitle={admin ? 'For NetriBeat administrators only.' : 'Use the email your recordings are tracked to.'}
      badge={admin ? 'Admin' : null}
      onSubmit={submit}
    >
      <Alert tone="success">{notice}</Alert>
      <Alert>{error}</Alert>
      <Field label="Email" type="email" autoComplete="email" inputMode="email" value={email} onChange={setEmail} error={emailErr} placeholder="name@institute.org" required />
      <Field label="Password" type="password" autoComplete="current-password" value={password} onChange={setPassword} error={pwErr} required />
      <div className="nb-row">
        <label className="nb-check">
          <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
          Keep me signed in
        </label>
        <Link className="nb-link" to="/forgot-password">Forgot password?</Link>
      </div>
      <Button type="submit" variant="primary" block busy={busy}>Sign in</Button>
      <p className="nb-auth-foot">
        {admin ? (
          <Link className="nb-link" to="/login">Back to user sign in</Link>
        ) : (
          <>New here? <Link className="nb-link" to="/register">Create an account</Link>{' · '}
            <Link className="nb-link" to="/admin/login">Administrator sign in</Link></>
        )}
      </p>
    </AuthLayout>
  );
}
