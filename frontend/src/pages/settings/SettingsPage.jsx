import { useAuth } from '../../auth/AuthContext.jsx';
import ProfileSection from './ProfileSection.jsx';
import SecuritySection from './SecuritySection.jsx';

/** Settings: your profile, password and signed-in devices on one page. */
export default function SettingsPage() {
  const { user } = useAuth();
  return (
    <>
      <header className="nb-page-head">
        <div>
          <h1 className="nb-page-title">Settings</h1>
          <p className="nb-muted">Your profile, password and the devices signed in to your account.</p>
        </div>
        <span className={`nb-badge ${user.role === 'admin' ? 'nb-badge-admin' : ''}`}>{user.role}</span>
      </header>
      <ProfileSection />
      <SecuritySection />
    </>
  );
}
