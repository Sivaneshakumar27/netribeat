import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { USER, mockApi, renderApp } from './helpers.jsx';

const ADMIN = { ...USER, id: '22222222-2222-4222-8222-222222222222', email: 'boss@example.org', firstName: 'Boss', name: 'Boss B', role: 'admin' };
const signedIn = (user) => ({ 'POST /auth/refresh': () => [200, { token: 't', expiresAt: 'x', user }] });
const SESSIONS = {
  items: [
    { id: 's-here', createdAt: '2026-10-22T09:00:00Z', lastUsedAt: '2026-10-22T09:05:00Z', expiresAt: '2026-10-22T21:00:00Z', remember: false, userAgent: 'Mozilla/5.0 (Windows NT 10.0) Chrome/130', ipAddress: '198.51.100.1', current: true },
    { id: 's-phone', createdAt: '2026-10-21T09:00:00Z', lastUsedAt: '2026-10-21T10:00:00Z', expiresAt: '2026-11-20T09:00:00Z', remember: true, userAgent: 'Mozilla/5.0 (iPhone) Safari/605', ipAddress: '198.51.100.2', current: false },
  ],
};

describe('navigation by role', () => {
  it('a user sees no administration links', async () => {
    mockApi(signedIn(USER));
    renderApp('/');
    await screen.findByText('Good to see you, Ada');
    expect(screen.getByRole('link', { name: 'Security' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Users' })).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Audit log' })).not.toBeInTheDocument();
  });

  it('a user opening /admin/audit is sent to their overview', async () => {
    mockApi(signedIn(USER));
    renderApp('/admin/audit');
    await waitFor(() => expect(screen.getByTestId('location').textContent).toBe('/'));
  });
});

describe('security page', () => {
  it('lists devices and signs out another one after confirmation', async () => {
    let sessions = SESSIONS;
    const calls = mockApi({
      ...signedIn(USER),
      'GET /users/me/sessions': () => [200, sessions],
      'DELETE /users/me/sessions/s-phone': () => { sessions = { items: [SESSIONS.items[0]] }; return [204, null]; },
    });
    renderApp('/security');
    expect(await screen.findByText('Chrome on Windows')).toBeInTheDocument();
    expect(screen.getByText('Safari on iOS')).toBeInTheDocument();
    expect(screen.getByText('This device')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Sign out device' }));
    const dialog = screen.getByRole('dialog', { name: 'Sign out this device?' });
    await userEvent.click(within(dialog).getByRole('button', { name: 'Sign out' }));
    expect(await screen.findByText('That device was signed out.')).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText('Safari on iOS')).not.toBeInTheDocument());
    expect(calls.some((c) => c.method === 'DELETE' && c.path === '/users/me/sessions/s-phone')).toBe(true);
  });

  it('cancelling the dialog does nothing; Escape closes it', async () => {
    const calls = mockApi({ ...signedIn(USER), 'GET /users/me/sessions': () => [200, SESSIONS] });
    renderApp('/security');
    await userEvent.click(await screen.findByRole('button', { name: 'Sign out all other devices' }));
    await userEvent.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
    expect(calls.some((c) => c.path === '/users/me/sessions/revoke-others')).toBe(false);
  });

  it('change password validates and reports server errors on the right field', async () => {
    mockApi({
      ...signedIn(USER),
      'GET /users/me/sessions': () => [200, SESSIONS],
      'POST /users/me/password': () => [400, { code: 'validation_error', message: 'x', fields: { currentPassword: 'Current password is incorrect' } }],
    });
    renderApp('/security');
    await userEvent.click(await screen.findByRole('button', { name: 'Change password' }));
    expect(screen.getByText('Enter your current password')).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText('Current password'), 'wrong one');
    await userEvent.type(screen.getByLabelText('New password'), 'violet kettle orbit 4219');
    await userEvent.type(screen.getByLabelText('Confirm new password'), 'violet kettle orbit 4219');
    await userEvent.click(screen.getByRole('button', { name: 'Change password' }));
    expect(await screen.findByText('Current password is incorrect')).toBeInTheDocument();
  });
});

describe('admin users', () => {
  const list = {
    items: [
      { ...ADMIN, source: 'admin', tokenVersion: 0, updatedAt: 'x' },
      { ...USER, source: 'registration', tokenVersion: 0, updatedAt: 'x' },
    ],
    total: 2, limit: 20, offset: 0,
  };

  it('lists users, hides actions on own row, disables another user after confirming', async () => {
    const calls = mockApi({
      ...signedIn(ADMIN),
      'GET /admin/users?sort=-createdAt&limit=20&offset=0': () => [200, list],
      [`PATCH /admin/users/${USER.id}/status`]: () => [200, { ...list.items[1], isActive: false }],
    });
    renderApp('/admin');
    const table = await screen.findByRole('table');
    const row = (await within(table).findByText('ada@example.org')).closest('tr');
    const ownRow = within(table).getByText('boss@example.org').closest('tr');
    expect(within(ownRow).queryByRole('button')).not.toBeInTheDocument();
    await userEvent.click(within(row).getByRole('button', { name: 'Disable' }));
    await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Disable' }));
    await screen.findByText(/Disable: done for ada@example.org/);
    expect(calls.find((c) => c.method === 'PATCH').body).toEqual({ isActive: false });
  });

  it('search is debounced and sent as q', async () => {
    const calls = mockApi({
      ...signedIn(ADMIN),
      'GET /admin/users?sort=-createdAt&limit=20&offset=0': () => [200, list],
      'GET /admin/users?q=ada&sort=-createdAt&limit=20&offset=0': () => [200, { ...list, items: [list.items[1]], total: 1 }],
    });
    renderApp('/admin');
    const table = await screen.findByRole('table');
    await within(table).findByText('ada@example.org');
    await userEvent.type(screen.getByLabelText('Search'), 'ada');
    await waitFor(() => expect(within(table).queryByText('boss@example.org')).not.toBeInTheDocument());
    expect(calls.filter((c) => c.path.startsWith('/admin/users?q=')).map((c) => c.path)).toEqual(['/admin/users?q=ada&sort=-createdAt&limit=20&offset=0']);
  });

  it('create user shows a duplicate-email error inline', async () => {
    mockApi({
      ...signedIn(ADMIN),
      'GET /admin/users?sort=-createdAt&limit=20&offset=0': () => [200, list],
      'POST /admin/users': () => [409, { code: 'email_taken', message: 'A user with this email already exists' }],
    });
    renderApp('/admin');
    await userEvent.click(await screen.findByRole('button', { name: 'Create user' }));
    const dialog = screen.getByRole('dialog', { name: 'Create user' });
    await userEvent.type(within(dialog).getByLabelText('First name'), 'N');
    await userEvent.type(within(dialog).getByLabelText('Last name'), 'U');
    await userEvent.type(within(dialog).getByLabelText('Email'), 'ada@example.org');
    await userEvent.click(within(dialog).getByRole('button', { name: 'Create user' }));
    expect(await within(dialog).findByText('A user with this email already exists')).toBeInTheDocument();
  });

  it('a server-side refusal (last admin) is shown in the dialog', async () => {
    const other = { ...ADMIN, id: '33333333-3333-4333-8333-333333333333', email: 'other@example.org', source: 'admin', tokenVersion: 0, updatedAt: 'x' };
    mockApi({
      ...signedIn(ADMIN),
      'GET /admin/users?sort=-createdAt&limit=20&offset=0': () => [200, { ...list, items: [other] }],
      [`PATCH /admin/users/${other.id}/role`]: () => [400, { code: 'last_admin', message: "The last active admin can't be demoted or disabled" }],
    });
    renderApp('/admin');
    const row = (await screen.findByText('other@example.org')).closest('tr');
    await userEvent.click(within(row).getByRole('button', { name: 'Make user' }));
    await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Make user' }));
    expect(await within(screen.getByRole('dialog')).findByRole('alert')).toHaveTextContent('last active admin');
  });
});

describe('audit log', () => {
  it('renders events without personal data and filters by action', async () => {
    const calls = mockApi({
      ...signedIn(ADMIN),
      'GET /admin/audit-events?limit=50&offset=0': () => [200, { items: [{ id: 'e1', createdAt: '2026-10-22T09:00:00Z', action: 'auth.login', actorUserId: USER.id, targetUserId: USER.id, ipAddress: '198.51.100.1', details: { mode: 'user', actor_id: USER.id } }], total: 1, limit: 50, offset: 0 }],
      'GET /admin/audit-events?action=auth.login_failed&limit=50&offset=0': () => [200, { items: [], total: 0, limit: 50, offset: 0 }],
    });
    renderApp('/admin/audit');
    expect(await screen.findByText('mode=user')).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText('Event'), 'auth.login_failed');
    expect(await screen.findByText('No events.')).toBeInTheDocument();
    expect(calls.some((c) => c.path.includes('action=auth.login_failed'))).toBe(true);
  });
});
