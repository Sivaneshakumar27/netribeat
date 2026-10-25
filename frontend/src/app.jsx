import { Navigate, Route, Routes, useLocation } from 'react-router-dom';
import { useAuth } from './auth/AuthContext.jsx';
import DashboardLayout from './components/DashboardLayout.jsx';
import AuditPage from './pages/admin/AuditPage.jsx';
import UsersPage from './pages/admin/UsersPage.jsx';
import ForgotPasswordPage from './pages/ForgotPasswordPage.jsx';
import LoginPage from './pages/LoginPage.jsx';
import NewPasswordPage from './pages/NewPasswordPage.jsx';
import AccountPage from './pages/AccountPage.jsx';
import DashboardPage from './pages/DashboardPage.jsx';
import SessionPage from './pages/SessionPage.jsx';
import SessionsPage from './pages/SessionsPage.jsx';
import SettingsPage from './pages/SettingsPage.jsx';
import UploadPage from './pages/UploadPage.jsx';
import RegisterPage from './pages/RegisterPage.jsx';
import ResetOtpPage from './pages/ResetOtpPage.jsx';
import SecurityPage from './pages/SecurityPage.jsx';
import VerifyEmailPage from './pages/VerifyEmailPage.jsx';

function Loading() {
  return <div className="nb-loading" role="status"><span className="nb-spinner" aria-hidden="true" /> Loading…</div>;
}

/** Signed-in area. The server enforces every permission; these guards only decide
 *  which screen to show. */
function RequireAuth({ children }) {
  const { status } = useAuth();
  const { pathname } = useLocation();
  if (status === 'loading') return <Loading />;
  if (status !== 'signed-in') {
    return <Navigate to={pathname.startsWith('/admin') ? '/admin/login' : '/login'} replace />;
  }
  return children;
}

function RequireAdmin({ children }) {
  const { status, user } = useAuth();
  if (status === 'loading') return <Loading />;
  if (status !== 'signed-in') return <Navigate to="/admin/login" replace />;
  if (user.role !== 'admin') return <Navigate to="/" replace />;
  return children;
}

function PublicOnly({ children }) {
  const { status, user } = useAuth();
  if (status === 'loading') return <Loading />;
  if (status === 'signed-in') return <Navigate to={user.role === 'admin' ? '/admin' : '/'} replace />;
  return children;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<PublicOnly><LoginPage mode="user" /></PublicOnly>} />
      <Route path="/admin/login" element={<PublicOnly><LoginPage mode="admin" /></PublicOnly>} />
      <Route path="/register" element={<PublicOnly><RegisterPage /></PublicOnly>} />
      <Route path="/verify-email" element={<PublicOnly><VerifyEmailPage /></PublicOnly>} />
      <Route path="/forgot-password" element={<PublicOnly><ForgotPasswordPage /></PublicOnly>} />
      <Route path="/reset/verify" element={<PublicOnly><ResetOtpPage /></PublicOnly>} />
      <Route path="/reset/new" element={<PublicOnly><NewPasswordPage /></PublicOnly>} />
      <Route element={<RequireAuth><DashboardLayout /></RequireAuth>}>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/sessions" element={<SessionsPage />} />
        <Route path="/sessions/:id" element={<SessionPage />} />
        <Route path="/upload" element={<UploadPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/account" element={<AccountPage />} />
        <Route path="/security" element={<SecurityPage />} />
        <Route path="/admin" element={<RequireAdmin><UsersPage /></RequireAdmin>} />
        <Route path="/admin/audit" element={<RequireAdmin><AuditPage /></RequireAdmin>} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
