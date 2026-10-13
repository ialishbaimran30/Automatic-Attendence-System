import React, { useEffect, useState } from 'react';
import { api } from './api';

export default function ClassifierControls({ run }) {
  const [status, setStatus] = useState(null), [busy, setBusy] = useState(false), [report, setReport] = useState(null);
  const refresh = async () => setStatus(await api('/classifier/status/'));
  useEffect(() => { run(refresh); }, []);
  async function train() {
    setBusy(true);
    try { const result = await run(() => api('/classifier/', 'POST', {})); if (result) { setReport(result); await run(refresh); } }
    finally { setBusy(false); }
  }
  return <div><h3>Custom classifier</h3><p>ArcFace stays frozen. Training uses encrypted stored enrollment embeddings; attendance scans never retrain it.</p>
    {status && <><p role="status">{status.detail} Classifier: {status.classifier.replaceAll('_',' ')}.</p>
      <p className="muted">{status.student_count} enrolled student(s). A batch of photos is one capture event; collect independent events, preferably on separate days.</p></>}
    <button disabled={busy} onClick={() => run(refresh)}>Refresh training readiness</button>
    <button disabled={busy || !status?.ready} onClick={train}>{busy ? 'Training on stored embeddings…' : 'Train / retrain classifier'}</button>
    <button disabled={busy} onClick={() => run(async () => setReport(await api('/classifier/')))}>View held-out classifier report</button>
    {report && <pre>{JSON.stringify(report,null,2)}</pre>}</div>;
}
