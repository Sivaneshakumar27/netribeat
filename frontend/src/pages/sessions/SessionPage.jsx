import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { ApiError, downloadFile, sessionsApi } from '../../api/client.js';
import LineChart from '../../charts/LineChart.jsx';
import PoincarePlot from '../../charts/PoincarePlot.jsx';
import Sparkline from '../../charts/Sparkline.jsx';
import ZoneBars from '../../charts/ZoneBars.jsx';
import { MetricTile, QualityBadge, StatusBadge, TypePill } from '../../components/badges.jsx';
import { ConfirmModal } from '../../components/Modal.jsx';
import { Alert, Button } from '../../components/ui.jsx';
import { formatDateTime } from '../../utils/format.js';
import { DEVICE_LABEL, duration, mmss, num, zoneColor } from '../../utils/session.js';
import AdvancedHrv from './AdvancedHrv.jsx';

const TABS = [['overview', 'Overview'], ['ecg', 'ECG & beats'], ['hr', 'Heart rate'], ['hrv', 'HRV analysis'], ['spec', 'HRV (spec §6)'], ['load', 'Load & respiration']];

function Unavailable({ m, k }) {
  return <p className="nb-muted">{m.unavailable?.[k] || 'Not available for this recording.'}</p>;
}

function pctOf(v, hrMax) { return v && hrMax ? `${Math.round((v / hrMax) * 100)} % of HRmax` : ''; }

function Overview({ m, sig }) {
  const hm = m.hrMax?.value;
  const td = m.timeDomain;
  const fd = m.frequencyDomain;
  return (
    <>
      <div className="nb-tiles nb-tiles-5">
        <MetricTile label="Avg HR" value={num(m.hr.avg, 0)} unit="bpm" />
        <MetricTile label="Max HR" value={num(m.hr.max, 0)} unit="bpm" sub={pctOf(m.hr.max, hm)} />
        <MetricTile label="Min HR" value={num(m.hr.min, 0)} unit="bpm" />
        <MetricTile label="RMSSD" value={num(td?.rmssd, 1)} unit="ms" />
        <MetricTile label="pNNI50" value={num(td?.pnni50, 1)} unit="%" />
        <MetricTile label="LF/HF" value={num(fd?.lfHf, 2)} sub={fd ? `LF ${num(fd.bands.lf.powerNu, 0)} n.u. · HF ${num(fd.bands.hf.powerNu, 0)} n.u.` : ''} />
        <MetricTile label="SD1" value={num(m.poincare?.sd1, 1)} unit="ms" sub={m.poincare ? `SD2 ${num(m.poincare.sd2, 1)} ms` : ''} />
        <MetricTile label="Respiratory rate" value={num(m.respiratoryRate?.value, 1)} unit="br/min" />
        <MetricTile label="Training load" value={num(m.trainingLoad, 0)} unit="AU" sub={m.trainingLoad === null ? (m.zonesUnavailableReason || '') : 'Banister TRIMP'} />
        <MetricTile label="Movement load" value={num(m.movementLoad, 2)} unit="RMS·h" sub={m.movementIntensity != null ? `intensity ${num(m.movementIntensity, 2)}` : ''} />
      </div>
      <div className="nb-split">
        <section className="nb-card"><h2 className="nb-card-title">Heart rate over time</h2><HrChart m={m} sig={sig} /></section>
        <section className="nb-card"><h2 className="nb-card-title">Zone distribution</h2><ZoneBars timeInZonesS={m.timeInZonesS} hrMax={hm?.value} reason={m.zonesUnavailableReason} /></section>
      </div>
    </>
  );
}

function HrChart({ m, sig }) {
  const hm = m.hrMax?.value;
  if (!sig.hr.tS.length) return <Unavailable m={m} k="hr" />;
  return (
    <LineChart title="Heart rate over time" describe={`average ${num(m.hr.avg, 0)} bpm`} height={240}
      series={[{ name: 'HR', unit: 'bpm', xs: sig.hr.tS, ys: sig.hr.bpm, color: 'var(--accent)', colorFor: hm ? (v) => zoneColor(v, hm) : undefined }]}
      bands={[{ from: 0, to: 300, label: 'HRV window', color: 'var(--band-hf)' }]}
      xFormat={mmss} yFormat={(v) => Math.round(v)} xLabel="Time" yLabel="bpm" />
  );
}

function EcgBeats({ m, sig }) {
  const [mode, setMode] = useState('hr');
  const strip = sig.ecgStrip;
  const b = m.beats;
  const rr = sig.rrRawMs;
  const flagged = new Set(sig.artefactIndices);
  const beatHr = (v) => 60000 / v;
  const ys = sig.rrCorrectedMs.map((v) => (mode === 'hr' ? beatHr(v) : v));
  const meanBeatHr = ys.length && mode === 'hr' ? ys.reduce((a, c) => a + c, 0) / ys.length : null;
  return (
    <>
      <div className="nb-tiles nb-tiles-4">
        <MetricTile label="Beats detected" value={b.detected} sub={`${b.rrIntervals} RR intervals`} />
        <MetricTile label="Artefacts corrected" value={b.artefacts} sub={`${num(b.artefactPct, 1)} %`} tone={b.artefactPct > 5 ? 'alert' : undefined} />
        <MetricTile label="Beat coverage" value={num((m.reliability.beatCoverage || 0) * 100, 0)} unit="%" tone={m.reliability.reliable ? undefined : 'alert'} sub="≥ 80 % expected" />
        <MetricTile label="Mean beat HR" value={num(meanBeatHr ?? (sig.rrCorrectedMs.length ? 60000 / (sig.rrCorrectedMs.reduce((a, c) => a + c, 0) / sig.rrCorrectedMs.length) : null), 0)} unit="bpm" />
      </div>
      {strip ? (
        <section className="nb-card"><h2 className="nb-card-title">ECG · first 10 s <span className="nb-muted nb-small">{strip.fs} Hz · {strip.unit === 'raw' ? 'raw units (unit not documented for this file format)' : strip.unit}</span></h2>
          <LineChart title="ECG strip" height={220}
            series={[{ name: 'ECG', unit: strip.unit === 'raw' ? '' : strip.unit, xs: strip.signal.map((_, i) => i / strip.fs), ys: strip.signal, color: 'var(--ink)' }]}
            markers={strip.rPeaks.map((p, i) => ({ x: p / strip.fs, y: strip.signal[p], label: i ? `${Math.round(((p - strip.rPeaks[i - 1]) / strip.fs) * 1000)}` : '' }))}
            xFormat={(v) => `${v.toFixed(1)} s`} yFormat={(v) => (Math.abs(v) >= 100 ? Math.round(v) : v.toFixed(2))} xLabel="Time" />
          <p className="nb-muted nb-small">Red rings: detected R-peaks. Numbers: RR interval to the previous peak (ms).</p>
        </section>
      ) : <section className="nb-card"><p className="nb-muted">This recording has RR intervals only (no raw ECG).</p></section>}
      <section className="nb-card">
        <div className="nb-card-head"><h2 className="nb-card-title">Beat to beat</h2>
          <div className="nb-seg" role="group" aria-label="Show">
            <button type="button" className={mode === 'hr' ? 'is-on' : ''} aria-pressed={mode === 'hr'} onClick={() => setMode('hr')}>HR (bpm)</button>
            <button type="button" className={mode === 'rr' ? 'is-on' : ''} aria-pressed={mode === 'rr'} onClick={() => setMode('rr')}>RR (ms)</button>
          </div></div>
        {ys.length ? (
          <LineChart title="Beat-to-beat series" height={240}
            series={[{ name: mode === 'hr' ? 'Beat HR' : 'RR', unit: mode === 'hr' ? 'bpm' : 'ms', xs: sig.beatTimesS, ys, color: 'var(--band-hf)' }]}
            markers={[...flagged].slice(0, 400).map((i) => {
              const cor = sig.rrCorrectedMs[i];
              const show = (v) => (mode === 'hr' ? `${Math.round(beatHr(v))} bpm` : `${Math.round(v)} ms`);
              return { x: sig.beatTimesS[i], y: mode === 'hr' ? beatHr(cor) : cor, color: 'var(--zone-5)', title: `Corrected beat: raw ${show(rr[i])} → ${show(cor)}` };
            })}
            xFormat={mmss} yFormat={(v) => Math.round(v)} xLabel="Time" />
        ) : <Unavailable m={m} k="hr" />}
        <p className="nb-muted nb-small">Line: corrected series. Red rings: beats corrected as artefacts (hover a ring for its raw value).</p>
      </section>
    </>
  );
}

function HeartRate({ m, sig }) {
  const hm = m.hrMax;
  return (
    <>
      <section className="nb-card">
        <h2 className="nb-card-title">Heart-rate summary</h2>
        <div className="nb-tiles nb-tiles-4">
          <MetricTile label="Min" value={num(m.hr.min, 0)} unit="bpm" sub={pctOf(m.hr.min, hm?.value)} />
          <MetricTile label="Avg" value={num(m.hr.avg, 0)} unit="bpm" sub={pctOf(m.hr.avg, hm?.value)} />
          <MetricTile label="Max" value={num(m.hr.max, 0)} unit="bpm" sub={pctOf(m.hr.max, hm?.value)} />
          <MetricTile label="HRmax used" value={hm ? hm.value : '—'} unit="bpm" sub={hm ? `${hm.label} · ${hm.detail}` : m.zonesUnavailableReason} />
        </div>
      </section>
      <section className="nb-card"><h2 className="nb-card-title">Heart rate over time</h2><HrChart m={m} sig={sig} /></section>
      <section className="nb-card"><h2 className="nb-card-title">Zone distribution</h2><ZoneBars timeInZonesS={m.timeInZonesS} hrMax={hm?.value} reason={m.zonesUnavailableReason} /></section>
    </>
  );
}

function Hrv({ m, sig }) {
  const [ratio, setRatio] = useState('lfhf');
  const td = m.timeDomain;
  const fd = m.frequencyDomain;
  if (!td) return <section className="nb-card"><Unavailable m={m} k="timeDomain" /></section>;
  const win = sig.rrCorrectedMs.slice(0, sig.hrvWindowBeats);
  const ref = (v, lo, hi) => (v >= lo && v <= hi ? 'within reference' : 'outside reference');
  const lfhf = fd?.lfHf;
  return (
    <>
      <section className="nb-card"><h2 className="nb-card-title">Time domain <span className="nb-muted nb-small">first 5 min, corrected RR</span></h2>
        <div className="nb-tiles nb-tiles-4">
          <MetricTile label="RMSSD" value={num(td.rmssd, 1)} unit="ms" sub={`19–75 ms · ${ref(td.rmssd, 19, 75)}`} />
          <MetricTile label="pNNI20" value={num(td.pnni20, 1)} unit="%" />
          <MetricTile label="pNNI50" value={num(td.pnni50, 1)} unit="%" sub={`3–45 % · ${ref(td.pnni50, 3, 45)}`} />
          <MetricTile label="SDNN" value={num(td.sdnn, 1)} unit="ms" />
          <MetricTile label="Mean RR" value={num(td.meanRr, 0)} unit="ms" />
          <MetricTile label="Mean HR" value={num(td.meanHr, 0)} unit="bpm" />
          <MetricTile label="Beats" value={td.beats} />
        </div>
      </section>
      <section className="nb-card"><div className="nb-card-head"><h2 className="nb-card-title">Frequency domain <span className="nb-muted nb-small">Lomb–Scargle</span></h2>
        <div className="nb-seg" role="group" aria-label="Ratio">
          <button type="button" className={ratio === 'lfhf' ? 'is-on' : ''} aria-pressed={ratio === 'lfhf'} onClick={() => setRatio('lfhf')}>LF/HF</button>
          <button type="button" className={ratio === 'hflf' ? 'is-on' : ''} aria-pressed={ratio === 'hflf'} onClick={() => setRatio('hflf')}>HF/LF</button>
        </div></div>
        {fd ? (
          <>
            <LineChart title="Power spectral density" height={230}
              series={[{ name: 'PSD', unit: 'ms²/Hz', xs: fd.freqs, ys: fd.power, color: 'var(--ink)' }]}
              bands={[['VLF', 'vlf', 'var(--band-vlf)'], ['LF', 'lf', 'var(--band-lf)'], ['HF', 'hf', 'var(--band-hf)']].map(([l, k, c]) => ({ from: fd.bands[k].rangeHz[0], to: fd.bands[k].rangeHz[1], label: l, color: c }))}
              markers={['lf', 'hf'].filter((k) => fd.bands[k].peakHz).map((k) => ({ x: fd.bands[k].peakHz, y: fd.power[fd.freqs.indexOf(fd.bands[k].peakHz)] ?? 0, color: k === 'lf' ? 'var(--band-lf)' : 'var(--band-hf)', label: `${fd.bands[k].peakHz.toFixed(3)} Hz` }))}
              xFormat={(v) => v.toFixed(2)} yFormat={(v) => (v >= 1000 ? `${(v / 1000).toFixed(1)}k` : Math.round(v))} xLabel="Hz" />
            <div className="nb-table-wrap"><table className="nb-table nb-table-compact">
              <thead><tr><th>Band</th><th>Range (Hz)</th><th>Peak (Hz)</th><th>Power (ms²)</th><th>%</th><th>n.u.</th></tr></thead>
              <tbody>{['vlf', 'lf', 'hf'].map((k) => { const bd = fd.bands[k]; return (
                <tr key={k}><td><b>{k.toUpperCase()}</b></td><td>{bd.rangeHz[0]}–{bd.rangeHz[1]}</td><td>{num(bd.peakHz, 3)}</td><td>{num(bd.power, 0)}</td><td>{num(bd.powerPct, 1)}</td><td>{num(bd.powerNu, 1)}</td></tr>); })}
                <tr><td><b>Total</b></td><td /><td /><td>{num(fd.totalPower, 0)}</td><td /><td /></tr></tbody>
            </table></div>
            <p>{ratio === 'lfhf' ? 'LF/HF' : 'HF/LF'}: <b>{lfhf ? (ratio === 'lfhf' ? lfhf : 1 / lfhf).toFixed(2) : '—'}</b></p>
          </>
        ) : <Unavailable m={m} k="frequencyDomain" />}
      </section>
      <section className="nb-card"><h2 className="nb-card-title">Poincaré</h2>
        <div className="nb-split nb-split-poincare">
          <PoincarePlot rr={win} sd1={m.poincare?.sd1} sd2={m.poincare?.sd2} />
          <div className="nb-tiles nb-tiles-2">
            <MetricTile label="SD1" value={num(m.poincare?.sd1, 1)} unit="ms" />
            <MetricTile label="SD2" value={num(m.poincare?.sd2, 1)} unit="ms" />
            <MetricTile label="SD1/SD2" value={num(m.poincare?.sd1Sd2, 3)} />
            <MetricTile label="Beats" value={win.length} />
          </div>
        </div>
      </section>
    </>
  );
}

function Meter({ value, max, bands, unit }) {
  const pct = Math.min(100, ((value || 0) / max) * 100);
  return (
    <div className="nb-meter" role="meter" aria-valuemin={0} aria-valuemax={max} aria-valuenow={value || 0} aria-label={`${value ?? 'n/a'} ${unit}`}>
      <div className="nb-meter-track"><span style={{ width: `${pct}%` }} /></div>
      <div className="nb-meter-scale">{bands.map(([l, v]) => <span key={l} style={{ left: `${(v / max) * 100}%` }}>{l}</span>)}</div>
    </div>
  );
}

function Load({ m, sig }) {
  const resp = sig.perMinute.respiratoryRate || [];
  return (
    <div className="nb-grid-2 nb-grid-gap">
      <section className="nb-card"><h2 className="nb-card-title">Training load</h2>
        <p className="nb-big">{num(m.trainingLoad, 0)} <span className="nb-muted">AU</span></p>
        {m.trainingLoad !== null ? <Meter value={m.trainingLoad} max={300} unit="AU" bands={[['Low', 0], ['Moderate', 50], ['High', 120], ['Very high', 200]]} />
          : <p className="nb-muted">{m.zonesUnavailableReason}</p>}
      </section>
      <section className="nb-card"><h2 className="nb-card-title">Movement load</h2>
        <p className="nb-big">{num(m.movementLoad, 2)} <span className="nb-muted">RMS·h</span></p>
        <p className="nb-muted">Intensity {num(m.movementIntensity, 2)} · {m.steps ?? '—'} steps</p>
      </section>
      <section className="nb-card"><h2 className="nb-card-title">Respiratory rate</h2>
        <p className="nb-big">{num(m.respiratoryRate?.value, 1)} <span className="nb-muted">br/min</span></p>
        <p className="nb-muted nb-small">From the HF peak ({num(m.respiratoryRate?.hfPeakHz, 3)} Hz). Normal at rest: 12–20 br/min.</p>
        <div className="nb-small nb-muted">Per minute (2-min windows · provisional rule P5)</div>
        <Sparkline values={resp} width={280} label="Respiratory rate per minute" />
      </section>
    </div>
  );
}

export default function SessionPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [session, setSession] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const [signals, setSignals] = useState(null);
  const [error, setError] = useState('');
  const [tab, setTab] = useState('overview');
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState('');

  const load = useCallback(async () => {
    try {
      const s = await sessionsApi.get(id);
      setSession(s);
      if (s.status === 'ready') {
        const [a, g] = await Promise.all([sessionsApi.analysis(id), sessionsApi.signals(id)]);
        setAnalysis(a.metrics);
        setSignals(g.signals);
      }
    } catch (e) {
      setError(e instanceof ApiError && e.status === 404 ? 'Session not found.' : e.message);
    }
  }, [id]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (session?.status !== 'processing') return undefined;
    const t = setInterval(load, 2500);
    return () => clearInterval(t);
  }, [session?.status, load]);

  async function dl(path) {
    setNotice('');
    try { setNotice(`Downloaded ${await downloadFile(path)}`); } catch (e) { setError(e.message); }
  }
  async function retry() {
    setBusy(true);
    try { setSession(await sessionsApi.retry(id)); setError(''); } catch (e) { setError(e.message); } finally { setBusy(false); }
  }
  async function remove() {
    setBusy(true);
    try { await sessionsApi.remove(id); navigate('/sessions', { replace: true }); } catch (e) { setError(e.message); setConfirm(false); } finally { setBusy(false); }
  }

  if (error && !session) return <><Link className="nb-link" to="/sessions">← Sessions</Link><Alert>{error}</Alert></>;
  if (!session) return <div className="nb-loading-inline" role="status"><span className="nb-spinner" aria-hidden="true" /> Loading session…</div>;
  const m = analysis;
  const base = `/sessions/${id}`;
  return (
    <>
      <Link className="nb-link" to="/sessions">← Sessions</Link>
      <header className="nb-page-head">
        <div>
          <h1 className="nb-page-title"><TypePill type={session.type} /> session · {formatDateTime(session.recordedAt)}</h1>
          <p className="nb-muted">
            {session.userName}{session.userEmail ? ` (${session.userEmail})` : ''} · age {session.age ?? 'unknown'}{session.age ? ` (${session.ageSource === 'file' ? 'from file' : 'entered'})` : ''}
            {' · '}{DEVICE_LABEL[session.device]} · {duration(session.durationS)} · <span className="nb-mono">{session.fileName}</span>
          </p>
        </div>
        <div className="nb-head-actions">
          <StatusBadge status={session.status} />
          <QualityBadge quality={session.quality} reliable={session.reliable} />
        </div>
      </header>
      <Alert tone="success">{notice}</Alert>
      <Alert>{error}</Alert>
      {session.status === 'processing' ? <section className="nb-card" role="status"><span className="nb-spinner" aria-hidden="true" /> Analysing… this page updates automatically.</section> : null}
      {session.status === 'failed' ? (
        <section className="nb-card nb-card-error">
          <h2 className="nb-card-title">Analysis failed</h2>
          <p>{session.error}</p>
          <Button variant="primary" onClick={retry} busy={busy}>Retry analysis</Button>
        </section>
      ) : null}
      {m && signals ? (
        <>
          {!m.reliability.reliable ? <div className="nb-alert nb-alert-error" role="alert"><b>Beat detection is unreliable for this recording.</b> {m.warnings[0]?.replace(/^Beat detection is unreliable: /, '')}</div> : null}
          {m.beats.artefacts ? <div className="nb-alert nb-alert-info">{m.beats.artefacts} beats ({num(m.beats.artefactPct, 1)} %) were corrected as artefacts — all HRV results use the corrected series.</div> : null}
          <div className="nb-tabs" role="tablist" aria-label="Analysis">
            {TABS.map(([k, l]) => (
              <button key={k} type="button" role="tab" id={`tab-${k}`} aria-selected={tab === k} aria-controls={`panel-${k}`} tabIndex={tab === k ? 0 : -1}
                className={`nb-tab${tab === k ? ' is-on' : ''}`} onClick={() => setTab(k)}
                onKeyDown={(e) => {
                  const i = TABS.findIndex(([x]) => x === tab);
                  if (e.key === 'ArrowRight') setTab(TABS[(i + 1) % TABS.length][0]);
                  if (e.key === 'ArrowLeft') setTab(TABS[(i + TABS.length - 1) % TABS.length][0]);
                }}>{l}</button>
            ))}
          </div>
          <div role="tabpanel" id={`panel-${tab}`} aria-labelledby={`tab-${tab}`} className="nb-tabpanel">
            {tab === 'overview' ? <Overview m={m} sig={signals} /> : null}
            {tab === 'ecg' ? <EcgBeats m={m} sig={signals} /> : null}
            {tab === 'hr' ? <HeartRate m={m} sig={signals} /> : null}
            {tab === 'hrv' ? <AdvancedHrv sessionId={id} metrics={m.advanced} series={signals.advanced}
              onUpdated={(am, as) => { setAnalysis((x) => ({ ...x, advanced: am })); setSignals((x) => ({ ...x, advanced: as })); }} /> : null}
            {tab === 'spec' ? <Hrv m={m} sig={signals} /> : null}
            {tab === 'load' ? <Load m={m} sig={signals} /> : null}
          </div>
          <section className="nb-card">
            <h2 className="nb-card-title">Report and exports</h2>
            <div className="nb-row-start nb-wrap">
              <Button variant="primary" onClick={() => dl(`${base}/report`)}>PDF report (HRV results + session)</Button>
              <Button onClick={() => dl(`${base}/export.json`)}>JSON (all results)</Button>
              <Button onClick={() => dl(`${base}/export.csv?dataset=metrics`)}>CSV metrics</Button>
              <Button onClick={() => dl(`${base}/export.csv?dataset=hr`)}>CSV heart rate (1 Hz)</Button>
              <Button onClick={() => dl(`${base}/export.csv?dataset=rr`)}>CSV beats</Button>
              <Button onClick={() => dl(`${base}/export.csv?dataset=psd`)}>CSV spectrum</Button>
              {session.files[0] ? <Button variant="ghost" onClick={() => dl(`${base}/files/${session.files[0].id}`)}>Original file</Button> : null}
            </div>
            {m.warnings.length > (m.reliability.reliable ? 0 : 1) ? (
              <details className="nb-details"><summary>Warnings and notes ({m.warnings.length})</summary>
                <ul>{m.warnings.map((w) => <li key={w}>{w}</li>)}</ul></details>
            ) : null}
            <details className="nb-details"><summary>Method and provisional rules</summary>
              <p className="nb-small">Analysis version {m.analysisVersion} · {m.source.format} · {m.source.samplingRateHz ? `${m.source.samplingRateHz} Hz · ` : ''}{m.source.unit}. Research estimates, not a validated clinical result.</p>
              <ul className="nb-small">{Object.entries(m.provisionalRules).map(([k, v]) => <li key={k}><b>{k}</b> (provisional): {v}</li>)}</ul>
            </details>
          </section>
        </>
      ) : null}
      <div className="nb-row-start"><Button variant="ghost" onClick={() => setConfirm(true)}>Delete session</Button></div>
      {confirm ? (
        <ConfirmModal title="Delete this session?" body="The recording, its analysis and the uploaded file are removed permanently." confirmLabel="Delete" danger busy={busy}
          onConfirm={remove} onClose={() => setConfirm(false)} />
      ) : null}
    </>
  );
}
