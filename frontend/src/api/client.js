// API client. The access token lives only in memory (never localStorage); the refresh
// token is an HttpOnly cookie the browser sends to /api/v1/auth only. On a 401 the client
// refreshes once (single-flight, shared by concurrent calls) and retries the request.

const BASE = '/api/v1';
const CSRF = { 'X-Requested-With': 'NetriBeat' };

let accessToken = null;
let refreshInFlight = null;
const listeners = new Set();

export function setAccessToken(token) {
  accessToken = token;
}
export function getAccessToken() {
  return accessToken;
}
/** Called when the session is definitely gone (refresh failed). */
export function onSessionLost(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export class ApiError extends Error {
  constructor(status, body) {
    super((body && body.message) || `Request failed (${status})`);
    this.status = status;
    this.code = (body && body.code) || 'error';
    this.fields = (body && body.fields) || {};
  }
}

async function parse(res) {
  if (res.status === 204) return null;
  const text = await res.text();
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return { message: 'Unexpected response from server' };
  }
}

async function raw(path, { method = 'GET', body, headers = {}, auth = true } = {}) {
  const h = { ...headers };
  if (body !== undefined) h['Content-Type'] = 'application/json';
  if (auth && accessToken) h.Authorization = `Bearer ${accessToken}`;
  let res;
  try {
    res = await fetch(BASE + path, {
      method,
      headers: h,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      credentials: 'same-origin',
    });
  } catch {
    throw new ApiError(0, { code: 'network', message: "Can't reach the server. Check your connection and try again." });
  }
  const data = await parse(res);
  if (!res.ok) throw new ApiError(res.status, data);
  return data;
}

/** Exchange the refresh cookie for a new access token. Returns the login payload or null. */
export function refreshSession() {
  if (!refreshInFlight) {
    refreshInFlight = raw('/auth/refresh', { method: 'POST', headers: CSRF, auth: false })
      .then((data) => {
        setAccessToken(data.token);
        return data;
      })
      .catch(() => {
        setAccessToken(null);
        return null;
      })
      .finally(() => {
        refreshInFlight = null;
      });
  }
  return refreshInFlight;
}

/** Authenticated request with one transparent refresh-and-retry on 401. */
export async function api(path, options = {}) {
  try {
    return await raw(path, options);
  } catch (err) {
    if (!(err instanceof ApiError) || err.status !== 401 || options.auth === false || !accessToken) throw err;
    const refreshed = await refreshSession();
    if (!refreshed) {
      listeners.forEach((fn) => fn());
      throw err;
    }
    return raw(path, options);
  }
}

export const authApi = {
  register: (b) => raw('/auth/register', { method: 'POST', body: b, auth: false }),
  verifyEmail: (b) => raw('/auth/verify-email', { method: 'POST', body: b, auth: false }),
  resendVerification: (email) => raw('/auth/resend-verification', { method: 'POST', body: { email }, auth: false }),
  login: (b) => raw('/auth/login', { method: 'POST', body: b, auth: false }),
  logout: () => raw('/auth/logout', { method: 'POST', headers: CSRF }),
  me: () => api('/auth/me'),
  forgotPassword: (email) => raw('/auth/forgot-password', { method: 'POST', body: { email }, auth: false }),
  verifyResetOtp: (b) => raw('/auth/verify-reset-otp', { method: 'POST', body: b, auth: false }),
  resetPassword: (b) => raw('/auth/reset-password', { method: 'POST', body: b, auth: false }),
  changePassword: (b) => api('/users/me/password', { method: 'POST', body: b }),
};

const qs = (params) => {
  const p = new URLSearchParams();
  Object.entries(params || {}).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== '') p.set(k, String(v));
  });
  const s = p.toString();
  return s ? `?${s}` : '';
};

export const accountApi = {
  sessions: () => api('/users/me/sessions'),
  revokeSession: (id) => api(`/users/me/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  revokeOtherSessions: () => api('/users/me/sessions/revoke-others', { method: 'POST' }),
  updateProfile: (b) => api('/users/me', { method: 'PATCH', body: b }),
};

export const adminApi = {
  listUsers: (params) => api(`/admin/users${qs(params)}`),
  createUser: (b) => api('/admin/users', { method: 'POST', body: b }),
  setActive: (id, isActive) => api(`/admin/users/${id}/status`, { method: 'PATCH', body: { isActive } }),
  setRole: (id, role) => api(`/admin/users/${id}/role`, { method: 'PATCH', body: { role } }),
  revokeSessions: (id) => api(`/admin/users/${id}/sessions/revoke-all`, { method: 'POST' }),
  audit: (params) => api(`/admin/audit-events${qs(params)}`),
};

export const sessionsApi = {
  list: (params) => api(`/sessions${qs(params)}`),
  get: (id) => api(`/sessions/${id}`),
  analysis: (id) => api(`/sessions/${id}/analysis`),
  signals: (id) => api(`/sessions/${id}/signals`),
  remove: (id) => api(`/sessions/${id}`, { method: 'DELETE' }),
  retry: (id) => api(`/sessions/${id}/retry`, { method: 'POST' }),
  hrMax: () => api('/users/me/hr-max'),
  setHrMax: (b) => api('/users/me/hr-max', { method: 'PUT', body: b }),
  userHrMax: (userId) => api(`/admin/users/${userId}/hr-max`),
  setUserHrMax: (userId, b) => api(`/admin/users/${userId}/hr-max`, { method: 'PUT', body: b }),
};

function xhrUpload(form, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${BASE}/sessions`);
    if (accessToken) xhr.setRequestHeader('Authorization', `Bearer ${accessToken}`);
    xhr.upload.onprogress = (e) => { if (e.lengthComputable && onProgress) onProgress(e.loaded / e.total); };
    xhr.onload = () => {
      let body = null;
      try { body = xhr.responseText ? JSON.parse(xhr.responseText) : null; } catch { body = null; }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body);
      else reject(new ApiError(xhr.status, body));
    };
    xhr.onerror = () => reject(new ApiError(0, { code: 'network', message: "Upload failed: can't reach the server." }));
    xhr.send(form);
  });
}

/** Multipart upload with progress (XMLHttpRequest exposes upload progress; fetch doesn't).
 *  Refreshes the access token once on 401 and retries. */
export async function uploadRecordings(form, onProgress) {
  try {
    return await xhrUpload(form, onProgress);
  } catch (err) {
    if (!(err instanceof ApiError) || err.status !== 401) throw err;
    if (!(await refreshSession())) {
      listeners.forEach((fn) => fn());
      throw err;
    }
    return xhrUpload(form, onProgress);
  }
}

/** Download an authenticated file (PDF, CSV, JSON) and save it in the browser. */
export async function downloadFile(path) {
  const go = () => fetch(BASE + path, { headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {} });
  let res = await go();
  if (res.status === 401 && (await refreshSession())) res = await go();
  if (!res.ok) throw new ApiError(res.status, await parse(res));
  const blob = await res.blob();
  const name = /filename="([^"]+)"/.exec(res.headers.get('content-disposition') || '')?.[1] || 'netribeat-download';
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  return name;
}

sessionsApi.reanalyse = (id, options) => api(`/sessions/${id}/advanced`, { method: 'POST', body: options });
