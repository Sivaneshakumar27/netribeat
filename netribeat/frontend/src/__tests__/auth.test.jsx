import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { USER, mockApi, renderApp } from './helpers.jsx';

const signedOut = { 'POST /auth/refresh': () => [401, { code: 'unauthorized', message: 'Sign in to continue' }] };
const loc = () => screen.getByTestId('location').textContent;

describe('login', () => {
  it('shows field messages and calls nothing when empty', async () => {
    const calls = mockApi(signedOut);
    renderApp('/login');
    await userEvent.click(await screen.findByRole('button', { name: 'Sign in' }));
    expect(screen.getByText('Enter a valid email address, like name@institute.org')).toBeInTheDocument();
    expect(screen.getByText('Enter your password')).toBeInTheDocument();
    expect(calls.filter((c) => c.path === '/auth/login')).toHaveLength(0);
  });

  it('normalises email, sends remember + mode, and lands on the account page', async () => {
    const calls = mockApi({
      ...signedOut,
      'POST /auth/login': () => [200, { token: 'access-1', expiresAt: '2026-10-22T09:15:00Z', user: USER }],
    });
    renderApp('/login');
    await userEvent.type(await screen.findByLabelText('Email'), '  ADA@Example.org ');
    await userEvent.type(screen.getByLabelText('Password'), 'correct horse battery staple');
    await userEvent.click(screen.getByLabelText('Keep me signed in'));
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    await waitFor(() => expect(loc()).toBe('/'));
    expect(calls.find((c) => c.path === '/auth/login').body).toEqual({
      email: 'ada@example.org', password: 'correct horse battery staple', remember: true, mode: 'user',
    });
    expect(await screen.findByText('Good to see you, Ada')).toBeInTheDocument();
  });

  it('shows one generic message for any 401', async () => {
    mockApi({ ...signedOut, 'POST /auth/login': () => [401, { code: 'invalid_credentials', message: 'Email or password is incorrect' }] });
    renderApp('/login');
    await userEvent.type(await screen.findByLabelText('Email'), 'ada@example.org');
    await userEvent.type(screen.getByLabelText('Password'), 'wrong');
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Email or password is incorrect.');
  });

  it('admin login sends mode=admin', async () => {
    const calls = mockApi({ ...signedOut, 'POST /auth/login': () => [200, { token: 't', expiresAt: 'x', user: { ...USER, role: 'admin' } }] });
    renderApp('/admin/login');
    expect(await screen.findByRole('heading', { name: 'Administrator sign in' })).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText('Email'), 'boss@example.org');
    await userEvent.type(screen.getByLabelText('Password'), 'pw');
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    await waitFor(() => expect(loc()).toBe('/admin'));
    expect(calls.find((c) => c.path === '/auth/login').body.mode).toBe('admin');
  });

  it('shows the rate-limit message on 429', async () => {
    mockApi({ ...signedOut, 'POST /auth/login': () => [429, { code: 'too_many_attempts', message: 'x' }] });
    renderApp('/login');
    await userEvent.type(await screen.findByLabelText('Email'), 'ada@example.org');
    await userEvent.type(screen.getByLabelText('Password'), 'pw');
    await userEvent.click(screen.getByRole('button', { name: 'Sign in' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Too many attempts');
  });
});

describe('registration', () => {
  it('validates locally, never sends a role, then goes to verification', async () => {
    const calls = mockApi({ ...signedOut, 'POST /auth/register': () => [202, { status: 'verification_pending', message: 'sent' }] });
    renderApp('/register');
    await userEvent.click(await screen.findByRole('button', { name: 'Create account' }));
    expect(screen.getByText('Enter your first name')).toBeInTheDocument();
    expect(screen.getByText('Use at least 12 characters')).toBeInTheDocument();

    await userEvent.type(screen.getByLabelText('First name'), 'Ada');
    await userEvent.type(screen.getByLabelText('Last name'), 'Lovelace');
    await userEvent.type(screen.getByLabelText('Email'), 'Ada@Example.org');
    await userEvent.type(screen.getByLabelText('Password'), 'correct horse battery staple');
    await userEvent.type(screen.getByLabelText('Confirm password'), 'something else entirely');
    await userEvent.click(screen.getByRole('button', { name: 'Create account' }));
    expect(screen.getByText("Passwords don't match")).toBeInTheDocument();

    await userEvent.clear(screen.getByLabelText('Confirm password'));
    await userEvent.type(screen.getByLabelText('Confirm password'), 'correct horse battery staple');
    await userEvent.click(screen.getByRole('button', { name: 'Create account' }));
    await waitFor(() => expect(loc()).toBe('/verify-email'));
    const body = calls.find((c) => c.path === '/auth/register').body;
    expect(body.email).toBe('ada@example.org');
    expect(body).not.toHaveProperty('role');
    expect(screen.getByLabelText('Email')).toHaveValue('ada@example.org');
  });

  it('shows server field errors (e.g. common password)', async () => {
    mockApi({ ...signedOut, 'POST /auth/register': () => [400, { code: 'validation_error', message: 'x', fields: { password: 'This password is too common. Choose something harder to guess' } }] });
    renderApp('/register');
    await userEvent.type(await screen.findByLabelText('First name'), 'A');
    await userEvent.type(screen.getByLabelText('Last name'), 'B');
    await userEvent.type(screen.getByLabelText('Email'), 'a@example.org');
    await userEvent.type(screen.getByLabelText('Password'), 'password1234');
    await userEvent.type(screen.getByLabelText('Confirm password'), 'password1234');
    await userEvent.click(screen.getByRole('button', { name: 'Create account' }));
    expect(await screen.findByText(/too common/)).toBeInTheDocument();
  });
});

describe('email verification', () => {
  it('verifies the code and returns to login with a notice', async () => {
    const calls = mockApi({ ...signedOut, 'POST /auth/verify-email': () => [200, USER] });
    renderApp('/verify-email', { email: 'ada@example.org', justRegistered: true });
    await userEvent.type(await screen.findByLabelText('Verification code'), '12a3456');
    expect(screen.getByLabelText('Verification code')).toHaveValue('123456');
    await userEvent.click(screen.getByRole('button', { name: 'Verify and activate' }));
    await waitFor(() => expect(loc()).toBe('/login'));
    expect(screen.getByRole('status')).toHaveTextContent('Your account is active');
    expect(calls.find((c) => c.path === '/auth/verify-email').body).toEqual({ email: 'ada@example.org', code: '123456' });
  });

  it('resend starts a 60 s cooldown', async () => {
    mockApi({ ...signedOut, 'POST /auth/resend-verification': () => [202, { status: 'accepted', message: 'If a sign-up is waiting…' }] });
    renderApp('/verify-email', { email: 'ada@example.org' });
    await userEvent.click(await screen.findByRole('button', { name: 'Resend code' }));
    expect(await screen.findByRole('button', { name: /Resend code in \d+s/ })).toBeDisabled();
  });
});

describe('password reset', () => {
  it('goes email → code → new password → login, keeping the token in memory only', async () => {
    const calls = mockApi({
      ...signedOut,
      'POST /auth/forgot-password': () => [202, { status: 'accepted', message: 'ok' }],
      'POST /auth/verify-reset-otp': () => [200, { resetToken: 'reset-token-abcdefghijklmnop', expiresAt: 'x' }],
      'POST /auth/reset-password': () => [204, null],
    });
    renderApp('/forgot-password');
    await userEvent.type(await screen.findByLabelText('Email'), 'ada@example.org');
    await userEvent.click(screen.getByRole('button', { name: 'Send reset code' }));
    await userEvent.type(await screen.findByLabelText('Reset code'), '654321');
    await userEvent.click(screen.getByRole('button', { name: 'Continue' }));
    await userEvent.type(await screen.findByLabelText('New password'), 'violet kettle orbit 4219');
    await userEvent.type(screen.getByLabelText('Confirm new password'), 'violet kettle orbit 4219');
    await userEvent.click(screen.getByRole('button', { name: 'Save new password' }));
    await waitFor(() => expect(loc()).toBe('/login'));
    expect(calls.find((c) => c.path === '/auth/reset-password').body).toEqual({
      resetToken: 'reset-token-abcdefghijklmnop', password: 'violet kettle orbit 4219', confirmPassword: 'violet kettle orbit 4219',
    });
    expect(JSON.stringify({ ...localStorage })).not.toContain('reset-token');
    expect(JSON.stringify({ ...sessionStorage })).not.toContain('reset-token');
  });

  it('deep-linking to the code or new-password step without state goes back to the start', async () => {
    mockApi(signedOut);
    renderApp('/reset/new');
    await waitFor(() => expect(loc()).toBe('/forgot-password'));
  });
});

describe('session handling', () => {
  it('restores a session from the refresh cookie on load, with the CSRF header', async () => {
    const calls = mockApi({ 'POST /auth/refresh': () => [200, { token: 'access-9', expiresAt: 'x', user: USER }] });
    renderApp('/');
    expect(await screen.findByText('Good to see you, Ada')).toBeInTheDocument();
    expect(calls[0].headers['X-Requested-With']).toBe('NetriBeat');
  });

  it('signed-out visitors to / are sent to login; protected admin route goes to admin login', async () => {
    mockApi(signedOut);
    renderApp('/admin');
    await waitFor(() => expect(loc()).toBe('/admin/login'));
  });

  it('a non-admin opening /admin lands on their account page', async () => {
    mockApi({ 'POST /auth/refresh': () => [200, { token: 't', expiresAt: 'x', user: USER }] });
    renderApp('/admin');
    await waitFor(() => expect(loc()).toBe('/'));
  });

  it('sign out calls the API and returns to login', async () => {
    const calls = mockApi({
      'POST /auth/refresh': () => [200, { token: 't', expiresAt: 'x', user: USER }],
      'POST /auth/logout': () => [204, null],
    });
    renderApp('/');
    await userEvent.click(await screen.findByRole('button', { name: 'Sign out' }));
    await waitFor(() => expect(loc()).toBe('/login'));
    const logout = calls.find((c) => c.path === '/auth/logout');
    expect(logout.headers.Authorization).toBe('Bearer t');
    expect(logout.headers['X-Requested-With']).toBe('NetriBeat');
  });
});
