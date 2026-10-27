import { NavLink, Outlet } from 'react-router-dom';
import { useAuth } from '../auth/AuthContext.jsx';
import { BrandMark, Wordmark } from './ui.jsx';

const icon = (d) => (
  <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
    <path d={d} fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
);
const I = {
  home: icon('M4 11 12 4l8 7v8a1 1 0 0 1-1 1h-5v-6h-4v6H5a1 1 0 0 1-1-1z'),
  users: icon('M9 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM2 21a7 7 0 0 1 14 0M17 11a3 3 0 1 0 0-6M22 21a6 6 0 0 0-4-5.6'),
  log: icon('M5 4h14v16H5zM8 8h8M8 12h8M8 16h5'),
  pulse: icon('M2 13h5l2-5 3 10 2.5-7 1.5 2H22'),
  list: icon('M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01'),
  upload: icon('M12 16V4M7 9l5-5 5 5M4 20h16'),
  sliders: icon('M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0M14 4v4M8 10v4M16 16v4'),
};

function Link({ to, end, children, ic }) {
  return (
    <NavLink to={to} end={end} className={({ isActive }) => `nb-side-link${isActive ? ' is-on' : ''}`}>
      {ic}
      <span>{children}</span>
    </NavLink>
  );
}

export default function DashboardLayout() {
  const { user, signOut } = useAuth();
  const admin = user.role === 'admin';
  return (
    <div className="nb-app">
      <aside className="nb-side">
        <div className="nb-side-brand"><BrandMark /><Wordmark /></div>
        <nav className="nb-side-nav" aria-label="Main">
          <span className="nb-side-label">Analysis</span>
          <Link to="/" end ic={I.home}>Dashboard</Link>
          <Link to="/sessions" ic={I.list}>Sessions</Link>
          <Link to="/upload" ic={I.upload}>New recording</Link>
          <span className="nb-side-label">Account</span>
          <Link to="/settings" ic={I.sliders}>Settings</Link>
          {admin ? (
            <>
              <span className="nb-side-label">Administration</span>
              <Link to="/admin" end ic={I.users}>Users</Link>
              <Link to="/admin/audit" ic={I.log}>Audit log</Link>
            </>
          ) : null}
        </nav>
        <div className="nb-side-foot">
          <span className="nb-side-email" title={user.email}>{user.email}</span>
          <span className="nb-side-role">{admin ? 'Administrator' : 'User'}</span>
          <button type="button" className="nb-side-signout" onClick={signOut}>Sign out</button>
        </div>
      </aside>
      <main className="nb-main" id="main">
        <Outlet />
      </main>
    </div>
  );
}
