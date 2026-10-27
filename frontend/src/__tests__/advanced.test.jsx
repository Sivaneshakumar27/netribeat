import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import ADV from './fixtures/advanced_d1blhr.json';
import { USER, mockApi, renderApp } from './helpers.jsx';

const SID = 'aaaaaaaa-0000-4000-8000-000000000002';
const signedIn = { 'POST /auth/refresh': () => [200, { token: 't', expiresAt: 'x', user: { ...USER, gender: null, heightCm: null, weightKg: null, hrRest: null } }] };
const DETAIL = {
  id: SID, userId: USER.id, userEmail: USER.email, userName: 'Ada L', type: 'rest', recordedAt: '2026-10-21T00:00:00Z',
  durationS: 305.8, status: 'ready', quality: 'good', reliable: true, avgHr: 74.4, maxHr: 90, rmssd: 68, trainingLoad: null,
  movementLoad: null, fileName: 'D1BLHR_RR.csv', age: 31, ageSource: 'form', recordedAtSource: 'upload_time', device: 'chest_strap_rr',
  notes: null, hrMaxManual: null, files: [{ id: 'f', name: 'D1BLHR_RR.csv', kind: 'rr', format: 'rr_text', sizeBytes: 1898, sha256: 'a'.repeat(64) }],
  artefactCount: 0, artefactPct: 0, hrvWindowS: [0, 300], error: null, attempts: 1, createdAt: 'x', processedAt: 'x',
};
const METRICS = {
  analysisVersion: '1.0.0', source: { format: 'rr_text', kind: 'rr', samplingRateHz: null, unit: 'ms', durationS: 305.8 },
  quality: 'good', hr: { min: 57, avg: 74.4, max: 90 }, beats: { detected: 376, rrIntervals: 376, artefacts: 0, artefactPct: 0 },
  reliability: { beatCoverage: 0.99, minBeatCoverage: 0.8, reliable: true }, hrvWindowS: [0, 300],
  timeDomain: null, frequencyDomain: null, poincare: null, respiratoryRate: { value: null }, movementLoad: null,
  hrMax: null, timeInZonesS: null, trainingLoad: null, zonesUnavailableReason: 'Max HR unknown', warnings: [], unavailable: {},
  provisionalRules: { P2: 'x' }, advanced: ADV.metrics,
};
const SIGNALS = { hr: { tS: [1, 2], bpm: [70, 71] }, beatTimesS: [], rrRawMs: [], rrCorrectedMs: [], artefactIndices: [], hrvWindowBeats: 0, ecgStrip: null, perMinute: { respiratoryRate: [] }, advanced: ADV.series };

const routes = (extra = {}) => ({
  ...signedIn,
  [`GET /sessions/${SID}`]: () => [200, DETAIL],
  [`GET /sessions/${SID}/analysis`]: () => [200, { sessionId: SID, metrics: METRICS }],
  [`GET /sessions/${SID}/signals`]: () => [200, { sessionId: SID, signals: SIGNALS }],
  ...extra,
});

describe('advanced HRV analysis', () => {
  it('shows Kubios-style results computed by the backend', async () => {
    mockApi(routes());
    renderApp(`/sessions/${SID}`);
    await userEvent.click(await screen.findByRole('tab', { name: 'HRV analysis' }));
    const td = ADV.metrics.timeDomain;
    const tdTable = screen.getByRole('heading', { name: 'Time-domain results' }).closest('section');
    expect(within(tdTable).getByText('RMSSD').closest('tr')).toHaveTextContent(td.rmssd.toFixed(1));
    expect(within(tdTable).getByText('pNN50').closest('tr')).toHaveTextContent(td.pnn50.toFixed(2));
    expect(within(tdTable).getByText('TINN')).toBeInTheDocument();
    const nl = screen.getByRole('heading', { name: 'Nonlinear results' }).closest('section');
    expect(within(nl).getByText('Sample entropy').closest('tr')).toHaveTextContent(ADV.metrics.nonlinear.sampen.toFixed(3));
    expect(screen.getByRole('img', { name: /Poincaré plot/ })).toBeInTheDocument();
    expect(screen.getByText(/PNS and SNS indexes: not available/)).toBeInTheDocument();
  });

  it('switches spectrum method between FFT, AR and Lomb–Scargle', async () => {
    mockApi(routes());
    renderApp(`/sessions/${SID}`);
    await userEvent.click(await screen.findByRole('tab', { name: 'HRV analysis' }));
    const fdSection = screen.getByRole('heading', { name: 'Frequency-domain results' }).closest('section');
    const lfhf = () => within(fdSection).getByText('LF/HF ratio').closest('tr').textContent;
    expect(lfhf()).toContain(ADV.metrics.frequencyDomain.fft.lfHf.toFixed(3));
    await userEvent.click(within(fdSection).getByRole('button', { name: 'AR' }));
    expect(lfhf()).toContain(ADV.metrics.frequencyDomain.ar.lfHf.toFixed(3));
    await userEvent.click(within(fdSection).getByRole('button', { name: 'Lomb–Scargle' }));
    expect(lfhf()).toContain(ADV.metrics.frequencyDomain.lomb.lfHf.toFixed(3));
  });

  it('recalculates with new options and shows the server result', async () => {
    const updated = { ...ADV.metrics, options: { ...ADV.metrics.options, correction: 'medium' }, sample: { ...ADV.metrics.sample, beatsCorrected: 9, beatsCorrectedPct: 2.45 } };
    const calls = mockApi(routes({ [`POST /sessions/${SID}/advanced`]: () => [200, { sessionId: SID, metrics: updated, series: ADV.series }] }));
    renderApp(`/sessions/${SID}`);
    await userEvent.click(await screen.findByRole('tab', { name: 'HRV analysis' }));
    await userEvent.selectOptions(screen.getByLabelText('Artefact correction'), 'medium');
    await userEvent.clear(screen.getByLabelText('Sample start (s)'));
    await userEvent.type(screen.getByLabelText('Sample start (s)'), '60');
    await userEvent.click(screen.getByRole('button', { name: 'Recalculate' }));
    await waitFor(() => expect(screen.getByText(/corrected \(2.45 %\)/)).toBeInTheDocument());
    const body = calls.find((c) => c.path === `/sessions/${SID}/advanced`).body;
    expect(body).toMatchObject({ correction: 'medium', sampleStartS: 60, sampleLengthS: 300, detrend: 'smoothness_priors' });
  });

  it('shows server validation errors from the options', async () => {
    mockApi(routes({ [`POST /sessions/${SID}/advanced`]: () => [400, { code: 'validation_error', message: 'x', fields: { options: 'the sample must start at ≥ 0 s and last ≥ 30 s' } }] }));
    renderApp(`/sessions/${SID}`);
    await userEvent.click(await screen.findByRole('tab', { name: 'HRV analysis' }));
    await userEvent.click(screen.getByRole('button', { name: 'Recalculate' }));
    expect(await screen.findByText(/last ≥ 30 s/)).toBeInTheDocument();
  });
});

describe('settings', () => {
  it('shows profile, password and devices on one page; old links redirect', async () => {
    const calls = mockApi({
      ...signedIn,
      'GET /users/me/sessions': () => [200, { items: [{ id: 's1', current: true, userAgent: 'Mozilla/5.0 (Windows NT 10.0) Chrome/130', ipAddress: '1.2.3.4', createdAt: '2026-10-20T10:00:00Z', lastUsedAt: '2026-10-20T10:00:00Z', expiresAt: '2026-11-20T10:00:00Z', remember: true }] }],
      'PATCH /users/me': (b) => [200, { ...USER, ...b, name: `${b.firstName} ${b.lastName}` }],
    });
    renderApp('/account');
    expect(await screen.findByRole('heading', { name: 'Settings' })).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Change password' })).toBeInTheDocument();
    expect(await screen.findByText('This device')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Edit name' }));
    const first = screen.getByLabelText('First name');
    await userEvent.clear(first);
    await userEvent.type(first, 'Grace');
    await userEvent.click(screen.getByRole('button', { name: 'Save' }));
    await screen.findByText('Profile saved.');
    expect(calls.find((c) => c.method === 'PATCH').body).toEqual({ firstName: 'Grace', lastName: USER.lastName });
  });
});


describe('upload accepts RR text files', () => {
  it('accepts .txt and lists it', async () => {
    mockApi(signedIn);
    vi.stubGlobal('XMLHttpRequest', class { open() {} setRequestHeader() {} send() {} });
    renderApp('/upload');
    await userEvent.upload(await screen.findByLabelText('Choose files'), new File(['812\n790\n'], 'rr.txt', { type: 'text/plain' }));
    expect(screen.getByText('rr.txt')).toBeInTheDocument();
    expect(screen.queryByText(/Only .json, .csv and .txt/)).not.toBeInTheDocument();
  });
});
