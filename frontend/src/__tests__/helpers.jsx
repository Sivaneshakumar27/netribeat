import { render } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { vi } from 'vitest';
import App from '../app.jsx';
import { AuthProvider } from '../auth/AuthContext.jsx';

const EMPTY_LIST = { items: [], total: 0, limit: 50, offset: 0, stats: { sessions: 0, users: 0, recordedTimeS: 0, avgRmssd: null } };

/** Route table of fake responses: { 'POST /auth/login': (body) => [status, json] }. */
export function mockApi(routes) {
  const calls = [];
  const fetchMock = vi.fn(async (url, init = {}) => {
    const method = init.method || 'GET';
    const path = url.replace('/api/v1', '');
    const body = init.body ? JSON.parse(init.body) : undefined;
    calls.push({ method, path, body, headers: init.headers || {} });
    const handler = routes[`${method} ${path}`]
      || (method === 'GET' && path.startsWith('/sessions?') ? () => [200, EMPTY_LIST] : undefined);
    const [status, json] = handler ? handler(body, init) : [404, { code: 'not_found', message: 'Not found' }];
    return new Response(json === null ? null : JSON.stringify(json), { status });
  });
  vi.stubGlobal('fetch', fetchMock);
  return calls;
}

export const USER = {
  id: '11111111-1111-4111-8111-111111111111', email: 'ada@example.org', firstName: 'Ada', lastName: 'L',
  name: 'Ada L', role: 'user', emailVerified: true, hasPassword: true, isActive: true, age: null,
  createdAt: '2026-10-22T09:00:00Z', lastLoginAt: null,
};

export function LocationProbe() {
  const loc = useLocation();
  return <div data-testid="location">{loc.pathname}</div>;
}

export function renderApp(path, state) {
  return render(
    <MemoryRouter initialEntries={[{ pathname: path, state }]}>
      <AuthProvider>
        <App />
        <Routes><Route path="*" element={<LocationProbe />} /></Routes>
      </AuthProvider>
    </MemoryRouter>,
  );
}
