import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { api, API } from './api';
import './style.css';
import ClassConfiguration from './ClassConfiguration';
import EnrollmentPhotos from './EnrollmentPhotos';
import ClassifierControls from './ClassifierControls';

function App() {
  const [user, setUser] = useState(null), [ready, setReady] = useState(false), [error, setError] = useState('');
  const [sections, setSections] = useState([]), [sectionId, setSectionId] = useState(''), [tab, setTab] = useState('session');
  const run = async (task) => { setError(''); try { return await task(); } catch (e) { setError(e.message); return null; } };
  useEffect(() => { if (location.pathname === '/enroll') { setReady(true); return; } api('/auth/me/').then(setUser).catch(() => {}).finally(() => setReady(true)); }, []);
  const refreshSections = async () => { const data = await api('/sections/'); setSections(data); setSectionId(current => data.some(s => String(s.id) === current) ? current : String(data[0]?.id || '')); };
  useEffect(() => { if (user) run(refreshSections); }, [user]);
  if (!ready) return <main>Loading…</main>;
  if (location.pathname === '/enroll') return <Enrollment />;
  if (!user) return <Login onLogin={setUser} />;
  const section = sections.find(s => String(s.id) === sectionId);
  return <><header><div><span className="eyebrow">UNIVERSITY · FACULTY PORTAL</span><h1>Attendance studio</h1></div><div>{user.first_name || user.username} <span className="badge">{user.role}</span><button onClick={() => run(async () => { await api('/auth/me/', 'DELETE'); setUser(null); })}>Sign out</button></div></header>
    <main><div className="toolbar"><label>Section <select value={sectionId} onChange={e => setSectionId(e.target.value)}>{sections.map(s => <option key={s.id} value={s.id}>{s.course_code} · {s.name} · {s.semester}</option>)}</select></label><nav>{['session', 'grid', 'enrollment', 'history', ...(user.role === 'admin' ? ['admin'] : [])].map(t => <button className={tab === t ? 'active' : ''} key={t} onClick={() => setTab(t)}>{t}</button>)}</nav></div>
    {error && <p role="alert" className="error">{error}</p>}
    {section ? <><p className="muted">{section.course_code} · Section {section.name} · Required attendance {section.effective_threshold}%</p>
      {tab === 'session' && <Session key={sectionId} section={section} run={run} />}
      {tab === 'grid' && <Grid key={sectionId} section={section} run={run} />}
      {tab === 'enrollment' && <EnrollmentAdmin key={sectionId} section={section} run={run} />}
      {tab === 'history' && <History key={sectionId} section={section} run={run} />}</> : <p>Create a course, section, schedule and student memberships in Administration.</p>}
    {tab === 'admin' && <Admin run={run} onChange={refreshSections} />}</main></>;
}

function Login({ onLogin }) {
  const [error, setError] = useState(''), [busy, setBusy] = useState(false);
  async function submit(e) { e.preventDefault(); setBusy(true); setError(''); const data = new FormData(e.currentTarget); try { onLogin(await api('/auth/login/', 'POST', Object.fromEntries(data))); } catch (err) { setError(err.message); } finally { setBusy(false); } }
  return <main className="login"><span className="eyebrow">UNIVERSITY ATTENDANCE</span><h1>Welcome, faculty.</h1><p>Start a class. Review each match. Confirm attendance.</p><form onSubmit={submit}><label>Username<input name="username" autoComplete="username" required /></label><label>Password<input name="password" type="password" autoComplete="current-password" required /></label><button className="primary" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button></form>{error && <p role="alert" className="error">{error}</p>}<p className="muted">Teachers and administrators only. Students are enrolled records.</p></main>;
}

function Session({ section, run }) {
  const [session, setSession] = useState(null), [schedule, setSchedule] = useState(String(section.schedules.at(-1)?.id || ''));
  const [job, setJob] = useState(null), [reason, setReason] = useState(''), [student, setStudent] = useState(''), [status, setStatus] = useState('present');
  const [camera, setCamera] = useState(false), [busy, setBusy] = useState(false), [sessions, setSessions] = useState([]);
  const [classSchedules, setClassSchedules] = useState(section.schedules);
  const video = useRef(null), stream = useRef(null);
  async function load() { const data = await api(`/sessions/?section=${section.id}`); setSessions(data); const open = data.find(s => !s.closed_at); setSession(current => current ? data.find(s => s.id === current.id) || open || null : open || null); }
  useEffect(() => { run(load); return () => stream.current?.getTracks().forEach(t => t.stop()); }, []);
  useEffect(() => { if (camera && video.current) { video.current.srcObject = stream.current; video.current.play().catch(() => {}); } }, [camera]);
  useEffect(() => {
    if (!job || !['queued', 'processing'].includes(job.status)) return;
    const interval = setInterval(() => run(async () => { const result = await api(`/jobs/${job.id}/`); setJob(result); }), 1200);
    return () => clearInterval(interval);
  }, [job?.id, job?.status]);
  async function start() { const data = await api(`/sections/${section.id}/start/`, 'POST', { schedule }); setSession(data); setJob(null); await load(); }
  async function capture() {
    setBusy(true);
    try {
      if (!video.current?.videoWidth) throw new Error('Wait for the webcam image.');
      const grant = await api(`/sessions/${session.id}/capture-grant/`, 'POST', {});
      const canvas = document.createElement('canvas'); canvas.width = video.current.videoWidth; canvas.height = video.current.videoHeight;
      canvas.getContext('2d').drawImage(video.current, 0, 0);
      const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', 0.92));
      const form = new FormData(); form.append('frame', blob, 'frame.jpg'); form.append('token', grant.token);
      setJob(await api(`/sessions/${session.id}/capture/`, 'POST', form));
    } finally { setBusy(false); }
  }
  const working = job && ['queued', 'processing'].includes(job.status);
  return <div className="columns"><section className="card"><h2>Class session</h2><ClassConfiguration section={section} run={run} onSaved={row => { setClassSchedules(rows => [...rows.filter(s => s.id !== row.id),row]); setSchedule(String(row.id)); }} /><label>Scheduled class<select value={schedule} onChange={e => setSchedule(e.target.value)}>{classSchedules.map(s => <option key={s.id} value={s.id}>{['Mon','Tue','Wed','Thu','Fri','Sat','Sun'][s.weekday]} {s.start_time}–{s.end_time} ({s.valid_from} → {s.valid_until})</option>)}</select></label>
    {!session || session.closed_at ? <button className="primary" disabled={!schedule} onClick={() => run(start)}>Start scheduled session</button> : <><p><b className="count">{session.checked_in_count}</b> / {session.roster.length} checked in</p><p>Grace: {session.grace_minutes} minutes from scheduled start.</p><button onClick={() => run(async () => { setSession(await api(`/sessions/${session.id}/close/`, 'POST', {})); setJob(null); await load(); })}>Close & mark remaining absent</button></>}
    <label>Review a session<select value={session?.id || ''} onChange={e => { setSession(sessions.find(s => s.id === e.target.value)); setJob(null); }}><option value="">Choose…</option>{sessions.map(s => <option key={s.id} value={s.id}>{new Date(s.scheduled_start).toLocaleString()} · {s.closed_at ? 'Closed' : 'Open'}</option>)}</select></label>
    {session && <><h3>{session.closed_at ? 'Closed roster' : 'Roster'}</h3><ul className="roster">{session.roster.map(r => <li key={r.student}>{r.name}<span className="badge">{session.records.find(a => a.student === r.student)?.status || 'Pending'}</span></li>)}</ul><label>Student<select value={student} onChange={e => setStudent(e.target.value)}><option value="">Choose…</option>{session.roster.map(r => <option key={r.student} value={r.student}>{r.name}</option>)}</select></label><label>Audit reason<input value={reason} onChange={e => setReason(e.target.value)} placeholder="Identity verified / correction explanation" /></label><div className="actions"><button disabled={!student || !reason.trim() || !!session.closed_at} onClick={() => run(async () => { await api(`/sessions/${session.id}/manual/`, 'POST', { student: Number(student), reason }); await load(); })}>Manual check-in</button><select aria-label="Correction status" value={status} onChange={e => setStatus(e.target.value)}>{['present','late','absent'].map(s => <option key={s}>{s}</option>)}</select><button disabled={!student || !reason.trim()} onClick={() => run(async () => { await api(`/sessions/${session.id}/correct/`, 'POST', { student: Number(student), status, reason }); await load(); })}>Correct record</button></div></>}
  </section><section className="card"><h2>Capture & review</h2><p className="muted">One student at a time. Good lighting, face centered, no photographs.</p><div className="camera">{camera ? <video ref={video} autoPlay playsInline muted /> : <p>Webcam preview</p>}</div><div className="actions"><button onClick={() => run(async () => { if (camera) { stream.current?.getTracks().forEach(t => t.stop()); setCamera(false); } else { stream.current = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480 }, audio: false }); setCamera(true); } })}>{camera ? 'Stop camera' : 'Enable camera'}</button><button className="primary" disabled={!camera || !session || !!session.closed_at || busy || working || job?.status === 'review'} onClick={() => run(capture)}>Capture student</button></div>
    {job && <div className="review" role="status"><b>{job.status.toUpperCase()}</b>{working && <p>Processing on the CPU…</p>}{job.status === 'review' && <><h3>{job.name}</h3><p>Cosine similarity: {job.score?.toFixed(3)}. This is not a probability.</p><p>Capture time: {new Date(job.captured_at).toLocaleTimeString()}. Review expires {new Date(job.expires_at).toLocaleTimeString()}.</p><button className="primary" onClick={() => run(async () => { await api(`/sessions/${session.id}/confirm/`, 'POST', { job: job.id }); setJob(null); await load(); })}>Confirm identity & save</button><button onClick={() => setJob(null)}>Discard suggestion</button></>}{job.reason && <p>{job.reason.replaceAll('_', ' ')}</p>}{job.action && <p>{job.action}</p>}</div>}
    <p className="muted">A match does not write attendance until you confirm. Manual check-in remains available if recognition fails.</p></section></div>;
}

function Grid({ section, run }) {
  const [data, setData] = useState(null), [month, setMonth] = useState('');
  const query = month ? `?month=${month}` : `?semester=${encodeURIComponent(section.semester)}`;
  useEffect(() => { run(async () => setData(await api(`/sections/${section.id}/grid/${query}`))); }, [month]);
  return <section className="card"><div className="toolbar"><h2>Attendance register</h2><label>Month<input type="month" value={month} onChange={e => setMonth(e.target.value)} /></label><a className="button" href={`${API}/sections/${section.id}/export/${query}`}>Download Excel</a></div><p className="muted">Present and late count equally. Denominator: closed sessions in which the student was on the roster. “—” means not eligible.</p>{data && <div className="table-scroll"><table><thead><tr><th>Student</th>{data.sessions.map(s => <th key={s.id}>{new Date(s.date).toLocaleDateString()}<br />{new Date(s.date).toLocaleTimeString([], { hour:'2-digit', minute:'2-digit' })}</th>)}<th>Attendance</th></tr></thead><tbody>{data.students.map(s => <tr key={s.student}><td>{s.name}<small>{s.registration_number}</small></td>{data.sessions.map(d => <td key={d.id}><span className={`status ${s.statuses[d.id] || ''}`}>{s.statuses[d.id] || '—'}</span></td>)}<td className={s.below_threshold ? 'flag' : ''}>{s.percentage === null ? 'No closed sessions' : `${s.percentage}% · ${s.attended}/${s.denominator}`}{s.below_threshold && <small>Below {data.threshold}%</small>}</td></tr>)}</tbody></table></div>}</section>;
}

function EnrollmentAdmin({ section, run }) {
  const [students, setStudents] = useState([]), [studentId, setStudentId] = useState(''), [link, setLink] = useState('');
  const [photos, setPhotos] = useState([]), [busy, setBusy] = useState(false), [message, setMessage] = useState('');
  const load = async () => setStudents(await api(`/students/?section=${section.id}`));
  useEffect(() => { run(load); }, []);
  async function upload(e) {
    e.preventDefault(); setBusy(true); setMessage('Uploading, checking one live face and extracting the frozen ArcFace embedding. First use may download model weights.');
    try {
      const form = new FormData(); form.set('consent', 'true'); photos.forEach(p => form.append('photos',p));
      const result = await run(() => api(`/students/${studentId}/bulk-enroll/`, 'POST', form));
      if (result) { setMessage(`${result.saved} encrypted sample(s) saved for all enrolled classes. Attendance unchanged. Collect independent events until training is ready.`); setPhotos([]); await run(load); }
      else setMessage('Enrollment failed; nothing saved. See the actionable error above and retry.');
    } finally { setBusy(false); }
  }
  const selected = students.find(s => String(s.id) === studentId);
  return <section className="card"><h2>Biometric enrollment</h2><p>Enroll each student once for reuse across enrolled classes. Add independent capture events to that same enrollment for classifier training; a batch is one event. Enrollment never records attendance.</p>
    <label>Student<select disabled={busy} value={studentId} onChange={e => { setStudentId(e.target.value); setLink(''); setPhotos([]); setMessage(''); }}><option value="">Choose…</option>{students.map(s => <option key={s.id} value={s.id}>{s.name} · {s.enrolled_samples} samples · {s.capture_groups} capture events</option>)}</select></label>
    {selected && <p role="status">{selected.capture_groups < 3 ? `Insufficient training data for this student: ${3-selected.capture_groups} more independent capture event(s) needed.` : 'Student has enough capture events; administrator can train once the enrollment cohort is ready.'}</p>}
    <button disabled={!studentId || busy} onClick={() => run(async () => { const data = await api(`/students/${studentId}/enrollment-link/`, 'POST', {}); setLink(data.url); })}>Create single-use selfie link (30 min)</button>{link && <p className="link"><a href={link} target="_blank" rel="noreferrer">{link}</a></p>}
    <form onSubmit={upload}><EnrollmentPhotos key={studentId} photos={photos} onPhotos={setPhotos} disabled={busy} />
      <label className="checkbox"><input type="checkbox" disabled={busy} required /> I have recorded the student’s explicit consent under the university biometric policy.</label>
      <button disabled={!studentId || !photos.length || busy}>{busy ? 'Validating and generating embeddings…' : 'Validate liveness & enroll photos'}</button>
    </form>{message && <p role="status">{message}</p>}</section>;
}

function Enrollment() {
  const [message, setMessage] = useState(''), [busy, setBusy] = useState(false);
  const [photos, setPhotos] = useState([]);
  const token = useRef(location.hash.slice(1));
  useEffect(() => { history.replaceState(null, '', '/enroll'); }, []);
  async function submit(e) { e.preventDefault(); setBusy(true); setMessage('Validating one live face and generating its ArcFace embedding. First use may download model weights.'); const form = new FormData(); photos.forEach(p => form.append('photos',p)); form.set('token', token.current); form.set('consent', 'true'); try { const result = await api('/enroll/', 'POST', form); setMessage(result.detail); token.current = ''; setPhotos([]); } catch (err) { setMessage(err.message); } finally { setBusy(false); } }
  return <main className="login"><h1>Enroll your selfie</h1><p>This single-use link expires after 30 minutes. This form cannot mark attendance. Provide a clear, recent photograph of yourself, alone, in good lighting.</p><p>Your photo and facial template are encrypted, accessed only by authorized staff, and retained for up to 365 days by default. You can request removal and manual attendance through your teacher. Face matching and liveness can make mistakes; a teacher reviews every attendance proposal.</p><form onSubmit={submit}><EnrollmentPhotos photos={photos} onPhotos={setPhotos} disabled={busy || !token.current} /><label className="checkbox"><input type="checkbox" disabled={busy} required /> I consent to encrypted facial data processing for class attendance under policy attendance-biometric-v1.</label><button className="primary" disabled={busy || !token.current || !photos.length}>{busy ? 'Validating…' : 'Submit enrollment'}</button></form>{message && <p role="status">{message}</p>}</main>;
}

function History({ section, run }) {
  const [logs, setLogs] = useState([]), [sessions, setSessions] = useState([]);
  useEffect(() => { run(async () => { setLogs(await api(`/audit/?section=${section.id}`)); setSessions(await api(`/sessions/?section=${section.id}`)); }); }, []);
  return <section className="card"><h2>Session history & audit</h2><p>{sessions.length} sessions · Open: {sessions.filter(s => !s.closed_at).length} · Closed: {sessions.filter(s => s.closed_at).length}</p><div className="table-scroll"><table><thead><tr><th>Time</th><th>Event</th><th>Actor ID</th><th>Details</th></tr></thead><tbody>{logs.map(l => <tr key={l.id}><td>{new Date(l.at).toLocaleString()}</td><td>{l.event}</td><td>{l.actor ?? 'System'}</td><td><code>{JSON.stringify(l.details)}</code></td></tr>)}</tbody></table></div></section>;
}

const schemas = {
  users: { username: '', first_name: '', last_name: '', role: 'teacher', is_active: true, password: '' },
  departments: { name: '' },
  courses: { department: 1, code: '', name: '', attendance_threshold: 75, grace_minutes: 10, match_threshold: 0.65, match_margin: 0.08 },
  sections: { course: 1, name: '', semester: 'Fall 2026', teachers: [], attendance_threshold: null, grace_minutes: null, match_threshold: null, match_margin: null },
  schedules: { section: 1, weekday: 0, start_time: '09:00', end_time: '10:00', valid_from: '2026-09-01', valid_until: '2026-12-31' },
  students: { registration_number: '', name: '', department: 1, active: true },
  memberships: { student: 1, section: 1 },
};
function Admin({ run, onChange }) {
  const [resource, setResource] = useState('departments'), [rows, setRows] = useState([]), [editing, setEditing] = useState(null), [form, setForm] = useState(schemas.departments), [report, setReport] = useState(null);
  const load = async () => setRows(await api(`/${resource}/`));
  useEffect(() => { setEditing(null); setForm({ ...schemas[resource] }); run(load); }, [resource]);
  function edit(row) { setEditing(row.id); setForm(Object.fromEntries(Object.keys(schemas[resource]).map(k => [k, k === 'password' ? '' : row[k]]))); }
  async function save(e) { e.preventDefault(); const values = { ...form }; if (editing && !values.password) delete values.password; await api(`/${resource}/${editing ? `${editing}/` : ''}`, editing ? 'PATCH' : 'POST', values); setEditing(null); setForm({ ...schemas[resource] }); await load(); await onChange(); }
  return <section className="card"><h2>Administration</h2><p className="muted">Create departments → courses → staff → sections → schedules → students → memberships. IDs are shown below. Weekdays: Monday 0 to Sunday 6. Blank section thresholds inherit course settings.</p><label>Manage<select value={resource} onChange={e => setResource(e.target.value)}>{Object.keys(schemas).map(r => <option key={r}>{r}</option>)}</select></label><div className="columns"><form onSubmit={e => { e.preventDefault(); run(() => save(e)); }}><h3>{editing ? `Edit #${editing}` : 'Create record'}</h3>{Object.entries(form).map(([key, value]) => <label key={key}>{key.replaceAll('_', ' ')}{typeof value === 'boolean' ? <input type="checkbox" checked={value} onChange={e => setForm({ ...form, [key]: e.target.checked })} /> : <input type={key === 'password' ? 'password' : 'text'} value={Array.isArray(value) ? value.join(',') : value ?? ''} placeholder={Array.isArray(value) ? 'Comma-separated teacher IDs' : value === null ? 'Inherit course default' : ''} onChange={e => { const v = e.target.value; const numeric = typeof schemas[resource][key] === 'number' || schemas[resource][key] === null; setForm({ ...form, [key]: Array.isArray(value) ? v.split(',').filter(Boolean).map(Number) : numeric ? v === '' ? null : Number(v) : v }); }} />}</label>)}<button className="primary">Save</button><button type="button" onClick={() => { setEditing(null); setForm({ ...schemas[resource] }); }}>Clear</button></form><div className="table-scroll"><table><thead><tr><th>ID</th><th>Record</th><th>Actions</th></tr></thead><tbody>{rows.map(r => <tr key={r.id}><td>{r.id}</td><td>{r.username || r.name || `${r.student} → section ${r.section}`}{resource === 'schedules' && `Section ${r.section} · day ${r.weekday} ${r.start_time}`}</td><td><button onClick={() => edit(r)}>Edit</button><button onClick={() => run(async () => { await api(`/${resource}/${r.id}/`, 'DELETE'); await load(); await onChange(); })}>Delete</button>{resource === 'students' && <button onClick={() => run(async () => { await api(`/students/${r.id}/purge-biometrics/`, 'POST', { reason: 'Admin consent withdrawal / retention request' }); await load(); })}>Remove biometric data</button>}</td></tr>)}</tbody></table></div></div><ClassifierControls run={run} /></section>;
}

createRoot(document.getElementById('root')).render(<App />);
