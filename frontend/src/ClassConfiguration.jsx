import React, { useState } from 'react';
import { api } from './api';

export default function ClassConfiguration({ section, run, onSaved }) {
  const [busy, setBusy] = useState(false), [message, setMessage] = useState('');
  const [date, setDate] = useState(() => new Intl.DateTimeFormat('en-CA', { timeZone: section.time_zone, year:'numeric', month:'2-digit', day:'2-digit' }).format(new Date()));
  const [time, setTime] = useState('09:00'), [duration, setDuration] = useState(60), [grace, setGrace] = useState(section.effective_grace_minutes ?? 10);
  async function save(e) {
    e.preventDefault(); setBusy(true); setMessage('');
    try {
      const result = await run(() => api(`/sections/${section.id}/configure-class/`, 'POST', {
        class_date: date, start_time: time, duration_minutes: Number(duration), grace_minutes: Number(grace),
      }));
      if (result) { onSaved(result); setMessage('Class saved. Start the session within 15 minutes before the class or during it.'); }
    } finally { setBusy(false); }
  }
  return <details><summary>Configure a dated class</summary><p className="muted">Times use {section.time_zone}. This adds a class to your assigned section.</p>
    <form onSubmit={save}><label>Class date<input type="date" value={date} onChange={e => setDate(e.target.value)} required /></label>
      <label>Start time<input type="time" value={time} onChange={e => setTime(e.target.value)} required /></label>
      <label>Duration (minutes)<input type="number" min="1" max="480" value={duration} onChange={e => setDuration(e.target.value)} required /></label>
      <label>Late grace (minutes)<input type="number" min="0" max={Math.min(Number(duration),120)} value={grace} onChange={e => setGrace(e.target.value)} required /></label>
      <button disabled={busy}>{busy ? 'Saving class…' : 'Save class'}</button>
    </form>{message && <p role="status">{message}</p>}</details>;
}
