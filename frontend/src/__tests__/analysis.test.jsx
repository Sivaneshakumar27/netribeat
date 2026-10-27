import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { localToIso } from '../pages/sessions/UploadPage.jsx';
import { USER, mockApi, renderApp } from './helpers.jsx';

const signedIn = (user = USER) => ({ 'POST /auth/refresh': () => [200, { token: 't', expiresAt: 'x', user }] });
const SID = 'aaaaaaaa-0000-4000-8000-000000000001';
const SUMMARY = {
  id: SID, userId: USER.id, userEmail: USER.email, userName: 'Ada L', type: 'rest', recordedAt: '2026-09-04T16:11:54Z',
  durationS: 409, status: 'ready', quality: 'good', reliable: true, avgHr: 80.7, maxHr: 92.8, rmssd: 24.1,
  trainingLoad: 6.3, movementLoad: null, movementIntensity: null, steps: null, fileName: 'D4BLHRV_BLHR.csv',
};
const DETAIL = {
  ...SUMMARY, age: 18, ageSource: 'file', recordedAtSource: 'file', device: 'chest_strap_rr', notes: null, hrMaxManual: null,
  files: [{ id: 'f1', name: 'D4BLHRV_BLHR.csv', kind: 'ecg', format: 'movesense_csv_ecg', sizeBytes: 1283599, sha256: 'a'.repeat(64) }],
  artefactCount: 3, artefactPct: 0.55, hrvWindowS: [0, 300], error: null, attempts: 1, createdAt: 'x', processedAt: 'x',
};
const band = (lo, hi, peak, p) => ({ rangeHz: [lo, hi], peakHz: peak, power: p, powerPct: 33.3, powerNu: 50 });
const METRICS = {
  analysisVersion: '1.0.0', source: { format: 'movesense_csv_ecg', kind: 'ecg', samplingRateHz: 200, unit: 'mV', durationS: 409 },
  quality: 'good', hr: { min: 73.2, avg: 80.7, max: 92.8 },
  beats: { detected: 550, rrIntervals: 549, artefacts: 3, artefactPct: 0.55 },
  reliability: { beatCoverage: 0.99, minBeatCoverage: 0.8, reliable: true },
  hrvWindowS: [0, 300],
  timeDomain: { meanRr: 745, meanHr: 80.5, sdnn: 29.9, rmssd: 24.1, pnni20: 30.2, pnni50: 4.4, beats: 402 },
  frequencyDomain: { freqs: [0.002, 0.1, 0.25, 0.5], power: [10, 900, 400, 1], bands: { vlf: band(0.0033, 0.04, 0.02, 100), lf: band(0.04, 0.15, 0.1, 500), hf: band(0.15, 0.4, 0.25, 200) }, totalPower: 800, lfHf: 2.45 },
  poincare: { sd1: 17.1, sd2: 39.0, sd1Sd2: 0.44 }, respiratoryRate: { value: 9.6, hfPeakHz: 0.16 },
  movementLoad: null, hrMax: { value: 192, method: 'age', label: 'Age-based', detail: '210 − age (age 18)' },
  timeInZonesS: { belowZ1: 0, z1: 200, z2: 0, z3: 0, z4: 0, z5: 0 }, trainingLoad: 3.3, zonesUnavailableReason: null,
  warnings: ['3 beats (0.5 %) were corrected as artefacts — all HRV results use the corrected series'],
  unavailable: { movementLoad: 'No accelerometer data in this recording' },
  provisionalRules: { P2: 'gaps', P3: '1 Hz', P4: 'range', P5: 'per minute' },
};
const SIGNALS = {
  hr: { tS: [1, 2, 3, 4], bpm: [78, 80, 82, 79] }, beatTimesS: [0.7, 1.4, 2.2, 3.0],
  rrRawMs: [700, 750, 1400, 760], rrCorrectedMs: [700, 750, 755, 760], artefactIndices: [2], hrvWindowBeats: 4,
  ecgStrip: { fs: 200, unit: 'mV', lead: 'ECG', signal: [0, 0.1, 1.2, 0.1, 0, 0.1, 1.1, 0.1], rPeaks: [2, 6] },
  perMinute: { movementLoad: null, respiratoryRate: [9.5, 9.7, null, 9.6] },
};

describe('upload', () => {
  it('validates files and ranges before sending', async () => {
    const calls = mockApi(signedIn());
    renderApp('/upload');
    await userEvent.click(await screen.findByRole('button', { name: /Upload and analyse/ }));
    expect(screen.getByText('Choose at least one hex file')).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText('Max HR override (optional)'), '300');
    expect(screen.getByText('Max HR must be 100–230 bpm')).toBeInTheDocument();
    const input = screen.getByLabelText('Choose files');
    await userEvent.upload(input, new File(['x'], 'photo.png', { type: 'image/png' }), { applyAccept: false });
    expect(screen.getByText('Only Synapse hex files (.txt or .hex) are supported')).toBeInTheDocument();
    expect(calls.some((c) => c.path === '/sessions')).toBe(false);
  });

  it('sends multipart form with the chosen fields and shows the created sessions', async () => {
    mockApi(signedIn());
    let sent = null;
    const xhrs = [];
    class FakeXHR {
      constructor() { this.upload = {}; this.headers = {}; xhrs.push(this); }
      open(m, u) { this.method = m; this.url = u; }
      setRequestHeader(k, v) { this.headers[k] = v; }
      send(body) {
        sent = body;
        this.upload.onprogress?.({ lengthComputable: true, loaded: 5, total: 10 });
        this.status = 202;
        this.responseText = JSON.stringify({ items: [{ ...DETAIL, status: 'processing' }] });
        this.onload();
      }
    }
    vi.stubGlobal('XMLHttpRequest', FakeXHR);
    renderApp('/upload');
    await userEvent.type(await screen.findByLabelText('Age at recording (optional)'), '29');
    await userEvent.click(screen.getByLabelText('Rest / baseline'));
    await userEvent.selectOptions(screen.getByLabelText('Gender (optional)'), 'female');
    await userEvent.type(screen.getByLabelText('Resting HR, bpm (optional)'), '55');
    await userEvent.upload(screen.getByLabelText('Choose files'), new File(['00'], 'ADA_2026-10-22_08_12_39.txt', { type: 'text/plain' }));
    await userEvent.click(screen.getByRole('button', { name: /Upload and analyse/ }));
    expect(await screen.findByRole('link', { name: 'Open →' })).toHaveAttribute('href', `/sessions/${SID}`);
    expect(xhrs[0].url).toBe('/api/v1/sessions');
    expect(xhrs[0].headers.Authorization).toBe('Bearer t');
    expect(sent.get('type')).toBe('rest');
    expect(sent.get('age')).toBe('29');
    expect(sent.get('gender')).toBe('female');
    expect(sent.get('restingHr')).toBe('55');
    expect(sent.has('heightCm')).toBe(false);
    expect(sent.getAll('files')[0].name).toBe('ADA_2026-10-22_08_12_39.txt');
    expect(sent.has('userId')).toBe(false);
  });

  it('converts local date-times to ISO with offset', () => {
    expect(localToIso('2026-09-01T07:00')).toMatch(/^2026-09-01T07:00:00[+-]\d\d:\d\d$/);
    expect(localToIso('')).toBeNull();
  });
});

describe('sessions list', () => {
  it('renders rows with quality badges and opens a session on Enter', async () => {
    mockApi({
      ...signedIn(),
      'GET /sessions?limit=50&offset=0': () => [200, { items: [SUMMARY, { ...SUMMARY, id: 'b', reliable: false, quality: 'poor', rmssd: null }], total: 2, limit: 50, offset: 0, stats: { sessions: 2, users: 1, recordedTimeS: 818, avgRmssd: 24.1 } }],
      [`GET /sessions/${SID}`]: () => [200, { ...DETAIL, status: 'processing' }],
    });
    renderApp('/sessions');
    const table = await screen.findByRole('table');
    expect(await within(table).findAllByText('Good')).toHaveLength(1);
    expect(within(table).getByText('Unreliable')).toBeInTheDocument();
    expect(within(table).getByText('N/A')).toBeInTheDocument();
    within(table).getAllByRole('row')[1].focus();
    await userEvent.keyboard('{Enter}');
    await waitFor(() => expect(screen.getByTestId('location').textContent).toBe(`/sessions/${SID}`));
  });
});

describe('session view', () => {
  const routes = () => ({
    ...signedIn(),
    [`GET /sessions/${SID}`]: () => [200, DETAIL],
    [`GET /sessions/${SID}/analysis`]: () => [200, { sessionId: SID, metrics: METRICS }],
    [`GET /sessions/${SID}/signals`]: () => [200, { sessionId: SID, signals: SIGNALS }],
  });

  it('shows the overview, artefact banner and every tab', async () => {
    mockApi(routes());
    renderApp(`/sessions/${SID}`);
    expect(await screen.findByText(/3 beats \(0.6 %\) were corrected/)).toBeInTheDocument();
    expect(screen.getByText('RMSSD').nextSibling).toHaveTextContent('24.1 ms');
    await userEvent.click(screen.getByRole('tab', { name: 'ECG & beats' }));
    expect(screen.getByText('Beats detected')).toBeInTheDocument();
    expect(screen.getByRole('img', { name: /ECG strip/ })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('tab', { name: 'HRV (spec §6)' }));
    expect(screen.getByText('2.45')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'HF/LF' }));
    expect(screen.getByText('0.41')).toBeInTheDocument();
    expect(screen.getByRole('img', { name: /Poincaré plot/ })).toBeInTheDocument();
    await userEvent.click(screen.getByRole('tab', { name: 'Heart rate' }));
    expect(screen.getByText(/210 − age \(age 18\)/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('tab', { name: 'Load & respiration' }));
    expect(screen.getByText(/Intensity — · — steps/)).toBeInTheDocument();
  });

  it('keyboard on a chart shows the crosshair tooltip', async () => {
    mockApi(routes());
    renderApp(`/sessions/${SID}`);
    const chart = await screen.findByRole('img', { name: /Heart rate over time/ });
    chart.focus();
    await userEvent.keyboard('{ArrowRight}');
    expect(screen.getByRole('status')).toHaveTextContent('78');
  });

  it('flags unreliable detection prominently', async () => {
    const m = { ...METRICS, reliability: { beatCoverage: 0.21, minBeatCoverage: 0.8, reliable: false },
      warnings: ['Beat detection is unreliable: valid beats cover only 21 % of the recording (expected ≥ 80 %).'] };
    mockApi({ ...routes(), [`GET /sessions/${SID}/analysis`]: () => [200, { sessionId: SID, metrics: m }] });
    renderApp(`/sessions/${SID}`);
    expect(await screen.findByText('Beat detection is unreliable for this recording.')).toBeInTheDocument();
  });

  it('failed session can be retried', async () => {
    let status = 'failed';
    const calls = mockApi({
      ...signedIn(),
      [`GET /sessions/${SID}`]: () => [200, { ...DETAIL, status, error: 'Samples must be a non-empty list' }],
      [`POST /sessions/${SID}/retry`]: () => { status = 'processing'; return [200, { ...DETAIL, status: 'processing' }]; },
    });
    renderApp(`/sessions/${SID}`);
    expect(await screen.findByText('Samples must be a non-empty list')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Retry analysis' }));
    expect(await screen.findByText(/Analysing/)).toBeInTheDocument();
    expect(calls.some((c) => c.method === 'POST' && c.path === `/sessions/${SID}/retry`)).toBe(true);
  });

  it('downloads the PDF with the auth header', async () => {
    const calls = mockApi({ ...routes(), [`GET /sessions/${SID}/report`]: () => [200, { ok: 1 }] });
    globalThis.URL.createObjectURL = vi.fn(() => 'blob:x');
    globalThis.URL.revokeObjectURL = vi.fn();
    renderApp(`/sessions/${SID}`);
    await userEvent.click(await screen.findByRole('button', { name: 'PDF report (HRV results + session)' }));
    await screen.findByText(/Downloaded/);
    expect(calls.find((c) => c.path.endsWith('/report')).headers.Authorization).toBe('Bearer t');
  });

  it('delete asks for confirmation, then returns to the list', async () => {
    const calls = mockApi({ ...routes(), [`DELETE /sessions/${SID}`]: () => [204, null] });
    renderApp(`/sessions/${SID}`);
    await userEvent.click(await screen.findByRole('button', { name: 'Delete session' }));
    await userEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Delete' }));
    await waitFor(() => expect(screen.getByTestId('location').textContent).toBe('/sessions'));
    expect(calls.some((c) => c.method === 'DELETE')).toBe(true);
  });

  it('an unknown or foreign session shows not found', async () => {
    mockApi({ ...signedIn(), [`GET /sessions/${SID}`]: () => [404, { code: 'not_found', message: 'Session not found' }] });
    renderApp(`/sessions/${SID}`);
    expect(await screen.findByText('Session not found.')).toBeInTheDocument();
  });
});

