import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { ApiError, adminApi, uploadRecordings } from '../api/client.js';
import { useAuth } from '../auth/AuthContext.jsx';
import { StatusBadge } from '../components/badges.jsx';
import { Alert, Button, Field } from '../components/ui.jsx';
import { DEVICES, SESSION_TYPES } from '../utils/session.js';

const MAX_BYTES = 20 * 1024 * 1024;
const MAX_FILES = 10;
const OK_EXT = /\.(txt|hex)$/i;

/** datetime-local value → ISO 8601 with the browser's UTC offset. */
export function localToIso(value) {
  if (!value) return null;
  const d = new Date(value);
  const off = -d.getTimezoneOffset();
  const sign = off >= 0 ? '+' : '-';
  const hh = String(Math.floor(Math.abs(off) / 60)).padStart(2, '0');
  const mm = String(Math.abs(off) % 60).padStart(2, '0');
  return `${value.length === 16 ? `${value}:00` : value}${sign}${hh}:${mm}`;
}

export default function UploadPage() {
  const { user } = useAuth();
  const admin = user.role === 'admin';
  const inputRef = useRef(null);
  const [files, setFiles] = useState([]);
  const [form, setForm] = useState({ type: 'training', device: 'synapse', recordedAt: '', age: '', gender: '', restingHr: '', heightCm: '', weightKg: '', hrMaxManual: '', notes: '', userId: '' });
  const [users, setUsers] = useState([]);
  const [tried, setTried] = useState(false);
  const [serverFields, setServerFields] = useState({});
  const [error, setError] = useState('');
  const [progress, setProgress] = useState(null);
  const [results, setResults] = useState(null);
  const [drag, setDrag] = useState(false);
  const set = (k) => (v) => setForm((s) => ({ ...s, [k]: v }));

  useEffect(() => {
    if (!admin) return;
    adminApi.listUsers({ limit: 200, sort: 'email' }).then((r) => setUsers(r.items)).catch(() => setUsers([]));
  }, [admin]);

  function addFiles(list) {
    setResults(null);
    setFiles((cur) => {
      const names = new Set(cur.map((f) => f.name + f.size));
      return [...cur, ...Array.from(list).filter((f) => !names.has(f.name + f.size))];
    });
  }

  const fileProblems = files.map((f) => (!OK_EXT.test(f.name) ? 'Only Synapse hex files (.txt or .hex) are supported'
    : f.size > MAX_BYTES ? 'Larger than 20 MB' : f.size === 0 ? 'The file is empty' : null));
  const local = {
    files: !files.length ? 'Choose at least one hex file' : files.length > MAX_FILES ? `Upload at most ${MAX_FILES} files at once` : null,
    age: form.age && !(Number(form.age) >= 8 && Number(form.age) <= 100) ? 'Age must be 8–100' : null,
    hrMaxManual: form.hrMaxManual && !(Number(form.hrMaxManual) >= 100 && Number(form.hrMaxManual) <= 230) ? 'Max HR must be 100–230 bpm' : null,
    restingHr: form.restingHr && !(Number(form.restingHr) >= 25 && Number(form.restingHr) <= 120) ? 'Resting HR must be 25–120 bpm' : null,
    heightCm: form.heightCm && !(Number(form.heightCm) >= 80 && Number(form.heightCm) <= 250) ? 'Height must be 80–250 cm' : null,
    weightKg: form.weightKg && !(Number(form.weightKg) >= 20 && Number(form.weightKg) <= 300) ? 'Weight must be 20–300 kg' : null,
  };
  const err = (k) => serverFields[k] || ((tried || k === 'hrMaxManual') ? local[k] : null);
  const ageNum = Number(form.age);
  const zonesNote = form.hrMaxManual && !local.hrMaxManual ? `Zones will use ${form.hrMaxManual} bpm (upload override) unless your saved setting says otherwise.`
    : form.age && !local.age ? `Zones will use ${Math.round(210 - 0.65 * ageNum)} bpm (210 − 0.65 × age) unless your saved setting says otherwise.`
      : 'Empty fields use your profile; anything missing shows as “—” in the report.';

  async function submit() {
    setTried(true);
    setError('');
    setServerFields({});
    if (Object.values(local).some(Boolean) || fileProblems.some(Boolean)) return;
    const fd = new FormData();
    files.forEach((f) => fd.append('files', f, f.name));
    fd.append('type', form.type);
    fd.append('device', form.device);
    if (form.recordedAt) fd.append('recordedAt', localToIso(form.recordedAt));
    if (form.age) fd.append('age', String(Number(form.age)));
    if (form.hrMaxManual) fd.append('hrMaxManual', String(Number(form.hrMaxManual)));
    if (form.gender) fd.append('gender', form.gender);
    ['restingHr', 'heightCm', 'weightKg'].forEach((k) => { if (form[k]) fd.append(k, String(Number(form[k]))); });
    if (form.notes.trim()) fd.append('notes', form.notes.trim());
    if (admin && form.userId) fd.append('userId', form.userId);
    setProgress(0);
    try {
      const r = await uploadRecordings(fd, setProgress);
      setResults(r.items);
      setFiles([]);
      setTried(false);
    } catch (e) {
      if (e instanceof ApiError && e.code === 'validation_error') { setServerFields(e.fields); setError(e.message); }
      else setError(e.status === 413 ? e.message || 'A file is larger than 20 MB' : e.message);
    } finally {
      setProgress(null);
    }
  }

  return (
    <>
      <header className="nb-page-head"><div><h1 className="nb-page-title">New recording</h1>
        <p className="nb-muted">Synapse sensor hex files (<b>.txt</b>, e.g. <code>NAME_2026-10-22_08_12_39.txt</code>). Each recording in a file becomes its own session.</p></div></header>
      <form className="nb-upload" onSubmit={(e) => { e.preventDefault(); submit(); }} noValidate>
        <section className="nb-card nb-stack-wide">
          <h2 className="nb-card-title"><span className="nb-step">1</span>Who and when <span className="nb-muted nb-small">· subject details for the report</span></h2>
          {admin ? (
            <div className="nb-field">
              <label className="nb-field-label" htmlFor="up-user">Track to user</label>
              <select id="up-user" className="nb-input" value={form.userId} onChange={(e) => set('userId')(e.target.value)}>
                <option value="">Myself ({user.email})</option>
                {users.filter((u) => u.id !== user.id).map((u) => <option key={u.id} value={u.id}>{u.email || u.name}</option>)}
              </select>
            </div>
          ) : null}
          <div className="nb-grid-2">
            <Field label="Age at recording (optional)" type="number" inputMode="numeric" value={form.age} onChange={set('age')} error={err('age')} min="8" max="100" />
            <Field label="Max HR override (optional)" type="number" inputMode="numeric" value={form.hrMaxManual} onChange={set('hrMaxManual')} error={err('hrMaxManual')} min="100" max="230" />
            <div className="nb-field"><label className="nb-field-label" htmlFor="up-gender">Gender (optional)</label>
              <select id="up-gender" className="nb-input" value={form.gender} onChange={(e) => set('gender')(e.target.value)}>
                <option value="">From profile</option><option value="female">Female</option><option value="male">Male</option><option value="other">Other</option>
              </select>{err('gender') ? <div className="nb-field-error">{err('gender')}</div> : null}</div>
            <Field label="Resting HR, bpm (optional)" type="number" inputMode="numeric" value={form.restingHr} onChange={set('restingHr')} error={err('restingHr')} min="25" max="120" />
            <Field label="Height, cm (optional)" type="number" inputMode="numeric" value={form.heightCm} onChange={set('heightCm')} error={err('heightCm')} min="80" max="250" />
            <Field label="Weight, kg (optional)" type="number" inputMode="decimal" value={form.weightKg} onChange={set('weightKg')} error={err('weightKg')} min="20" max="300" />
          </div>
          <p className="nb-muted nb-small">{zonesNote}</p>
          <Field label="Recorded on (optional)" type="datetime-local" value={form.recordedAt} onChange={set('recordedAt')} error={err('recordedAt')}
            hint="Empty: taken from the file name (NAME_YYYY-MM-DD_HH_MM_SS), otherwise the upload time." />
        </section>
        <section className="nb-card nb-stack-wide">
          <h2 className="nb-card-title"><span className="nb-step">2</span>Session</h2>
          <fieldset className="nb-chips"><legend className="nb-field-label">Session type</legend>
            {SESSION_TYPES.map(([v, l]) => (
              <label key={v} className={`nb-chip${form.type === v ? ' is-on' : ''}`}>
                <input type="radio" name="type" value={v} checked={form.type === v} onChange={() => set('type')(v)} />{l}
              </label>
            ))}
          </fieldset>
          <div className="nb-field">
            <label className="nb-field-label" htmlFor="up-device">Device</label>
            <select id="up-device" className="nb-input" value={form.device} onChange={(e) => set('device')(e.target.value)}>
              {DEVICES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </div>
          <div className="nb-field">
            <label className="nb-field-label" htmlFor="up-notes">Notes (optional)</label>
            <textarea id="up-notes" className="nb-input nb-textarea" maxLength={500} value={form.notes} onChange={(e) => set('notes')(e.target.value)} />
          </div>
        </section>
        <section className="nb-card nb-stack-wide">
          <h2 className="nb-card-title"><span className="nb-step">3</span>Files</h2>
          <div
            className={`nb-drop${drag ? ' is-drag' : ''}${err('files') ? ' is-invalid' : ''}`}
            onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
            onDrop={(e) => { e.preventDefault(); setDrag(false); addFiles(e.dataTransfer.files); }}
          >
            <p><b>Drop Synapse hex files (.txt) here</b></p>
            <p className="nb-muted nb-small">Up to {MAX_FILES} files, 20 MB each</p>
            <Button onClick={() => inputRef.current?.click()}>Choose files</Button>
            <input ref={inputRef} type="file" accept=".txt,.hex,text/plain" multiple hidden aria-label="Choose files"
              onChange={(e) => { addFiles(e.target.files); e.target.value = ''; }} />
          </div>
          {err('files') ? <div className="nb-field-error">{err('files')}</div> : null}
          {files.length ? (
            <ul className="nb-list">
              {files.map((f, i) => (
                <li key={f.name + f.size} className="nb-list-row">
                  <div><b>{f.name}</b> <span className="nb-muted nb-small">{(f.size / 1024).toFixed(0)} KB</span>
                    {fileProblems[i] || serverFields[`files.${i}`] ? <div className="nb-field-error">{serverFields[`files.${i}`] || fileProblems[i]}</div> : null}</div>
                  <Button variant="ghost" onClick={() => setFiles((cur) => cur.filter((x) => x !== f))} aria-label={`Remove ${f.name}`}>Remove</Button>
                </li>
              ))}
            </ul>
          ) : null}
        </section>
        <Alert>{error}</Alert>
        {results ? (
          <section className="nb-card" aria-live="polite">
            <h2 className="nb-card-title">Uploaded</h2>
            <ul className="nb-list">
              {results.map((s) => (
                <li key={s.id} className="nb-list-row">
                  <div><b>{s.fileName}</b> <StatusBadge status={s.status} />{s.error ? <div className="nb-field-error">{s.error}</div> : null}</div>
                  <Link className="nb-link" to={`/sessions/${s.id}`}>Open →</Link>
                </li>
              ))}
            </ul>
          </section>
        ) : null}
        <div className="nb-sticky-bar">
          <span className="nb-muted">{files.length} file{files.length === 1 ? '' : 's'} · {form.type}</span>
          {progress !== null ? <progress className="nb-progress" value={progress} max={1} aria-label="Upload progress">{Math.round(progress * 100)} %</progress> : null}
          <Link className="nb-btn nb-btn-secondary" to="/sessions">Cancel</Link>
          <Button type="submit" variant="primary" busy={progress !== null}>Upload and analyse →</Button>
        </div>
      </form>
    </>
  );
}
