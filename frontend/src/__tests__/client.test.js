import { describe, expect, it } from 'vitest';
import { api, setAccessToken } from '../api/client.js';
import { mockApi } from './helpers.jsx';

describe('api client', () => {
  it('refreshes once on 401 and retries; concurrent calls share one refresh', async () => {
    let token = 'old';
    const calls = mockApi({
      'GET /auth/me': (_b, init) => (init.headers.Authorization === 'Bearer new' ? [200, { ok: true }] : [401, { code: 'unauthorized' }]),
      'POST /auth/refresh': () => { token = 'new'; return [200, { token: 'new', expiresAt: 'x', user: {} }]; },
    });
    setAccessToken('old');
    const results = await Promise.all([api('/auth/me'), api('/auth/me'), api('/auth/me')]);
    expect(results).toEqual([{ ok: true }, { ok: true }, { ok: true }]);
    expect(calls.filter((c) => c.path === '/auth/refresh')).toHaveLength(1);
    expect(token).toBe('new');
  });

  it('surfaces a friendly network error', async () => {
    globalThis.fetch = async () => { throw new TypeError('Failed to fetch'); };
    await expect(api('/auth/me')).rejects.toMatchObject({ status: 0, code: 'network' });
  });
});
