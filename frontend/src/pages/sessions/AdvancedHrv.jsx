import { useState } from 'react';
import { ApiError, sessionsApi } from '../../api/client.js';
import BarChart from '../../charts/BarChart.jsx';
import LineChart from '../../charts/LineChart.jsx';
import PoincarePlot from '../../charts/PoincarePlot.jsx';
import ScatterChart from '../../charts/ScatterChart.jsx';
import { MetricTile } from '../../components/badges.jsx';
import { Alert, Button } from '../../components/ui.jsx';
import { mmss, num } from '../../utils/session.js';

const CORRECTIONS = [
  ['none', 'None'], ['very_low', 'Very low (450 ms)'], ['low', 'Low (350 ms)'], ['medium', 'Medium (250 ms)'],
  ['strong', 'Strong (150 ms)'], ['very_strong', 'Very strong (50 ms)'], ['spec', 'NetriBeat rule (20 % of local median)'],
];
const hms = (s) => {
  const v = Math.round(s || 0);
  return `${String(Math.floor(v / 3600)).padStart(2, '0')}:${String(Math.floor((v % 3600) / 60)).padStart(2, '0')}:${String(v % 60).padStart(2, '0')}`;
};

function Options({ initial, onApply, busy, error }) {
  const [o, setO] = useState({
    sampleStartS: initial.sample_start_s ?? 0,
    sampleLengthS: initial.sample_length_s ?? '',
    correction: initial.correction ?? 'low',
    detrend: initial.detrend ?? 'smoothness_priors',
    smoothnessLambda: initial.smoothness_lambda ?? 500,
    arOrder: initial.ar_order ?? 16,
    tvWindowS: initial.tv_window_s ?? 60,
  });
  const set = (k) => (e) => setO((s) => ({ ...s, [k]: e.target.value }));
  const submit = (e) => {
    e.preventDefault();
    onApply({
      sampleStartS: Number(o.sampleStartS) || 0,
      sampleLengthS: o.sampleLengthS === '' ? null : Number(o.sampleLengthS),
      correction: o.correction,
      detrend: o.detrend,
      smoothnessLambda: Number(o.smoothnessLambda),
      arOrder: Number(o.arOrder),
      tvWindowS: Number(o.tvWindowS),
      tvStepS: Math.max(1, Math.round(Number(o.tvWindowS) / 6)),
    });
  };
  return (
    <form className="nb-card nb-adv-options" onSubmit={submit} aria-label="Analysis options">
      <h2 className="nb-card-title">Analysis options</h2>
      <div className="nb-adv-grid">
        <label className="nb-field"><span className="nb-field-label">Sample start (s)</span>
          <input className="nb-input" type="number" min="0" value={o.sampleStartS} onChange={set('sampleStartS')} /></label>
        <label className="nb-field"><span className="nb-field-label">Sample length (s, empty = to end)</span>
          <input className="nb-input" type="number" min="30" value={o.sampleLengthS} onChange={set('sampleLengthS')} /></label>
        <label className="nb-field"><span className="nb-field-label">Artefact correction</span>
          <select className="nb-input" value={o.correction} onChange={set('correction')}>
            {CORRECTIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></label>
        <label className="nb-field"><span className="nb-field-label">Trend removal</span>
          <select className="nb-input" value={o.detrend} onChange={set('detrend')}>
            <option value="smoothness_priors">Smoothness priors</option><option value="none">None</option></select></label>
        <label className="nb-field"><span className="nb-field-label">Smoothness λ</span>
          <input className="nb-input" type="number" min="1" max="100000" value={o.smoothnessLambda} onChange={set('smoothnessLambda')} disabled={o.detrend === 'none'} /></label>
        <label className="nb-field"><span className="nb-field-label">AR model order</span>
          <input className="nb-input" type="number" min="2" max="40" value={o.arOrder} onChange={set('arOrder')} /></label>
        <label className="nb-field"><span className="nb-field-label">Time-varying window (s)</span>
          <input className="nb-input" type="number" min="10" max="600" value={o.tvWindowS} onChange={set('tvWindowS')} /></label>
      </div>
      <Alert>{error}</Alert>
      <div className="nb-row-start"><Button type="submit" variant="primary" busy={busy}>Recalculate</Button>
        <span className="nb-muted nb-small">Threshold levels are given at 60 bpm and scale with the mean RR. Results are saved and used in the PDF.</span></div>
    </form>
  );
}

function Table({ head, rows }) {
  return (
    <div className="nb-table-wrap"><table className="nb-table nb-table-compact">
      <thead><tr>{head.map((h) => <th key={h}>{h}</th>)}</tr></thead>
      <tbody>{rows.map((r) => <tr key={r[0] + r[1]}>{r.map((c, i) => <td key={i /* eslint-disable-line react/no-array-index-key */}>{c}</td>)}</tr>)}</tbody>
    </table></div>
  );
}

export default function AdvancedHrv({ sessionId, metrics, series, onUpdated }) {
  const [method, setMethod] = useState('fft');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const m = metrics;
  const s = series;

  async function apply(opts) {
    setBusy(true);
    setError('');
    try {
      const r = await sessionsApi.reanalyse(sessionId, opts);
      onUpdated(r.metrics, r.series);
    } catch (e) {
      setError(e instanceof ApiError && e.fields?.options ? e.fields.options : e.message);
    } finally {
      setBusy(false);
    }
  }

  const options = <Options initial={m?.options || {}} onApply={apply} busy={busy} error={error} />;
  if (!m || m.unavailable?.all) {
    return <>{options}<section className="nb-card"><p className="nb-muted">{m?.unavailable?.all || 'Advanced HRV is not available for this recording.'}</p></section></>;
  }
  const td = m.timeDomain;
  const fd = m.frequencyDomain[method];
  const nl = m.nonlinear;
  const rq = nl.recurrence || {};
  const smp = s.sample;
  const spec = s.spectrum[method];
  const hist = s.histogram;
  const tv = s.timeVarying;

  return (
    <>
      {options}
      <section className="nb-card">
        <div className="nb-adv-head">
          <div><b>Sample</b> {hms(m.sample.startS)} – {hms(m.sample.startS + m.sample.lengthS)} ({hms(m.sample.lengthS)}) of {hms(m.sample.measurementLengthS)}</div>
          <div><b>{m.sample.beats}</b> beats · <b>{m.sample.beatsCorrected}</b> corrected ({num(m.sample.beatsCorrectedPct, 2)} %) · trend removal: {m.options.detrend === 'none' ? 'none' : `smoothness priors (λ ${m.options.smoothness_lambda})`}</div>
        </div>
        {m.warnings.map((w) => <div key={w} className="nb-alert nb-alert-info">{w}</div>)}
        <h3 className="nb-subtitle">RR data</h3>
        <LineChart title="RR tachogram" height={200}
          series={[{ name: 'RR', unit: 'ms', xs: s.tachogram.tS, ys: s.tachogram.rrMs, color: 'var(--band-hf)' },
            ...(smp.tS.length ? [{ name: 'Trend', unit: 'ms', xs: smp.tS, ys: smp.trendMs, color: 'var(--zone-5)' }] : [])].slice(0, 1)}
          bands={smp.tS.length ? [{ from: smp.tS[0], to: smp.tS[smp.tS.length - 1], label: 'Sample', color: 'var(--band-hf)' }] : []}
          markers={s.tachogram.flags.slice(0, 300).map((i) => ({ x: s.tachogram.tS[i], y: s.tachogram.rrMs[i], color: 'var(--zone-5)' }))}
          xFormat={mmss} yFormat={(v) => Math.round(v)} xLabel="Time" yLabel="RR (ms)" />
        <h3 className="nb-subtitle">Analysed sample with trend</h3>
        <LineChart title="Analysed sample" height={180}
          series={[{ name: 'RR', unit: 'ms', xs: smp.tS, ys: smp.rrMs, color: 'var(--band-hf)' }, { name: 'Trend', unit: 'ms', xs: smp.tS, ys: smp.trendMs, color: 'var(--zone-5)' }]}
          xFormat={mmss} yFormat={(v) => Math.round(v)} xLabel="Time" />
      </section>

      <section className="nb-card"><h2 className="nb-card-title">Autonomic nervous system</h2>
        <div className="nb-tiles nb-tiles-3">
          <MetricTile label="PNS · Mean RR" value={num(m.ans.pns.meanRr, 0)} unit="ms" />
          <MetricTile label="PNS · RMSSD" value={num(m.ans.pns.rmssd, 1)} unit="ms" />
          <MetricTile label="PNS · SD1" value={num(m.ans.pns.sd1Pct, 1)} unit="%" />
          <MetricTile label="SNS · Mean HR" value={num(m.ans.sns.meanHr, 0)} unit="bpm" />
          <MetricTile label="SNS · Stress index" value={num(m.ans.sns.stressIndex, 1)} />
          <MetricTile label="SNS · SD2" value={num(m.ans.sns.sd2Pct, 1)} unit="%" />
        </div>
        <p className="nb-muted nb-small">PNS and SNS indexes: not available. {m.ans.indexUnavailableReason}.</p>
      </section>

      <div className="nb-grid-2 nb-grid-gap">
        <section className="nb-card"><h2 className="nb-card-title">Time-domain results</h2>
          <Table head={['Variable', 'Units', 'Value']} rows={[
            ['Mean RR*', 'ms', num(td.meanRr, 0)], ['Mean HR*', 'bpm', num(td.meanHr, 0)], ['Min HR*', 'bpm', num(td.minHr, 0)],
            ['Max HR*', 'bpm', num(td.maxHr, 0)], ['SD HR', 'bpm', num(td.sdHr, 2)], ['SDNN', 'ms', num(td.sdnn, 1)],
            ['RMSSD', 'ms', num(td.rmssd, 1)], ['NN50', 'beats', td.nn50], ['pNN50', '%', num(td.pnn50, 2)],
            ['HRV triangular index', '', num(td.triangularIndex, 2)], ['TINN', 'ms', num(td.tinn, 1)], ['Stress index', '', num(td.stressIndex, 1)],
          ]} />
          <p className="nb-muted nb-small">* non-detrended RR data. Min/max HR: 5-beat moving average.</p>
        </section>
        <section className="nb-card"><h2 className="nb-card-title">RR distribution</h2>
          <BarChart title="RR histogram" unit="beats" valueFormat={(v) => v.toFixed(0)}
            items={hist.counts.map((c, i) => ({ label: '', value: c, color: 'var(--band-hf)', sub: `${Math.round(hist.edgesMs[i])}–${Math.round(hist.edgesMs[i + 1])} ms` }))} />
          <p className="nb-muted nb-small">Bins of 7.8125 ms (1/128 s), used for the triangular index and TINN.</p>
        </section>
      </div>

      <section className="nb-card">
        <div className="nb-card-head"><h2 className="nb-card-title">Frequency-domain results</h2>
          <div className="nb-seg" role="group" aria-label="Spectrum method">
            {[['fft', 'FFT (Welch)'], ['ar', 'AR'], ['lomb', 'Lomb–Scargle']].map(([k, l]) => (
              <button key={k} type="button" className={method === k ? 'is-on' : ''} aria-pressed={method === k} onClick={() => setMethod(k)}>{l}</button>))}
          </div></div>
        <div className="nb-split">
          <Table head={['Variable', 'Units', 'VLF', 'LF', 'HF']} rows={[
            ['Frequency band', 'Hz', '0.00–0.04', '0.04–0.15', '0.15–0.40'],
            ['Peak frequency', 'Hz', ...['vlf', 'lf', 'hf'].map((k) => num(fd.bands[k].peakHz, 3))],
            ['Power', 'ms²', ...['vlf', 'lf', 'hf'].map((k) => num(fd.bands[k].power, 0))],
            ...(fd.bands.vlf.logPower !== undefined ? [['Power', 'log', ...['vlf', 'lf', 'hf'].map((k) => num(fd.bands[k].logPower, 3))]] : []),
            ['Power', '%', ...['vlf', 'lf', 'hf'].map((k) => num(fd.bands[k].powerPct, 2))],
            ['Power', 'n.u.', '', num(fd.bands.lf.powerNu, 2), num(fd.bands.hf.powerNu, 2)],
            ['Total power', 'ms²', num(fd.totalPower, 0), '', ''],
            ['LF/HF ratio', '', num(fd.lfHf, 3), '', ''],
          ]} />
          <LineChart title={`${method.toUpperCase()} spectrum`} height={220}
            series={[{ name: 'PSD', unit: 'ms²/Hz', xs: spec.freqs, ys: spec.power, color: 'var(--ink)' }]}
            bands={[['VLF', 0, 0.04, 'var(--band-vlf)'], ['LF', 0.04, 0.15, 'var(--band-lf)'], ['HF', 0.15, 0.4, 'var(--band-hf)']].map(([l, a, b, c]) => ({ from: a, to: b, label: l, color: c }))}
            xFormat={(v) => v.toFixed(2)} yFormat={(v) => (v >= 1000 ? `${(v / 1000).toFixed(1)}k` : Math.round(v))} xLabel="Hz" />
        </div>
      </section>

      <section className="nb-card"><h2 className="nb-card-title">Nonlinear results</h2>
        <div className="nb-split nb-split-3">
          <Table head={['Variable', 'Units', 'Value']} rows={[
            ['Poincaré SD1', 'ms', num(nl.sd1, 1)], ['Poincaré SD2', 'ms', num(nl.sd2, 1)], ['SD2/SD1', '', num(nl.sd2Sd1, 3)],
            ['Approximate entropy', '', num(nl.apen, 3)], ['Sample entropy', '', num(nl.sampen, 3)],
            ['DFA α1', '', num(nl.dfaAlpha1, 3)], ['DFA α2', '', num(nl.dfaAlpha2, 3)],
            ['Recurrence REC', '%', num(rq.rec, 2)], ['Recurrence DET', '%', num(rq.det, 2)],
            ['Lmean / Lmax', 'beats', `${num(rq.lmean, 2)} / ${rq.lmax ?? '—'}`], ['ShanEn', '', num(rq.shanEn, 3)],
          ]} />
          <PoincarePlot rr={smp.detrendedMs.map((v) => v + (smp.rrMs.reduce((a, b) => a + b, 0) / smp.rrMs.length))} sd1={nl.sd1} sd2={nl.sd2} />
          <ScatterChart title="Detrended fluctuation analysis" height={260} xLabel="log10 n (beats)" yLabel="log10 F(n)"
            groups={[{ name: 'short', label: `α1 ${num(nl.dfaAlpha1, 2)}`, color: 'var(--band-lf)', points: s.dfa.short },
              { name: 'long', label: `α2 ${num(nl.dfaAlpha2, 2)}`, color: 'var(--band-hf)', points: s.dfa.long }]} />
        </div>
        {Object.keys(m.unavailable || {}).length ? <p className="nb-muted nb-small">{Object.entries(m.unavailable).map(([k, v]) => `${k}: ${v}`).join(' · ')}</p> : null}
      </section>

      {tv.tS.length > 1 ? (
        <section className="nb-card"><h2 className="nb-card-title">Time-varying analysis <span className="nb-muted nb-small">{m.options.tv_window_s} s window</span></h2>
          <LineChart title="Time-varying HRV" height={220}
            series={[{ name: 'RMSSD', unit: 'ms', xs: tv.tS, ys: tv.rmssd, color: 'var(--band-hf)' }, { name: 'Mean HR', unit: 'bpm', xs: tv.tS, ys: tv.meanHr, color: 'var(--accent)' }]}
            xFormat={mmss} yFormat={(v) => Math.round(v)} xLabel="Time" />
        </section>
      ) : null}
    </>
  );
}
