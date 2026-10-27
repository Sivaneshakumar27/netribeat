import { fireEvent, screen } from '@testing-library/react';
import { USER, mockApi, renderApp } from './helpers.jsx';

// Regression: the page cleared the file input before React read its (live) FileList, so the
// chosen file vanished when the update ran late — which happened on the admin page.
it.each([['user', USER], ['admin', { ...USER, role: 'admin' }]])('%s: a chosen file stays listed after the input is cleared', async (_, who) => {
  mockApi({
    'POST /auth/refresh': () => [200, { token: 't', expiresAt: 'x', user: who }],
    'GET /admin/users?limit=200&sort=email': () => [200, { items: [], total: 0, limit: 200, offset: 0 }],
  });
  renderApp('/upload');
  const input = await screen.findByLabelText('Choose files');
  const file = new File(['00'], 'BOOPATHI R_2026-10-22_08_12_39.txt', { type: 'text/plain' });
  const live = [file];
  Object.defineProperty(input, 'files', { configurable: true, get: () => live });
  Object.defineProperty(input, 'value', { configurable: true, get: () => '', set: () => { live.length = 0; } });
  fireEvent.change(input);
  expect(await screen.findByText('BOOPATHI R_2026-10-22_08_12_39.txt')).toBeInTheDocument();
  expect(screen.getByText(/^1 file/)).toBeInTheDocument();
});
