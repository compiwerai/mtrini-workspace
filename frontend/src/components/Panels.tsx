import React, { useEffect, useState } from 'react';
import { api } from '../api/client';

export function AutomationsView({ onRun }: { onRun: (threadId: string, prompt: string) => void }) {
  const [items, setItems] = useState<any[]>([]);
  const [name, setName] = useState('');
  const [prompt, setPrompt] = useState('');

  const load = async () => {
    try { setItems((await api.automations()).automations || []); } catch { setItems([]); }
  };
  useEffect(() => { load(); }, []);

  const save = async () => {
    if (!name.trim() || !prompt.trim()) return;
    await api.saveAutomation(name.trim(), prompt.trim());
    setName(''); setPrompt(''); load();
  };

  return (
    <div className="view">
      <h2>Automations</h2>
      <p style={{ color: 'var(--muted)' }}>Saved prompts you can re-run in one click. Running creates a thread seeded with the prompt.</p>
      <div className="card">
        <label className="f">Name</label>
        <input className="t" value={name} onChange={(e) => setName(e.target.value)} placeholder="Morning test run" />
        <label className="f">Prompt</label>
        <textarea className="t" value={prompt} onChange={(e) => setPrompt(e.target.value)} rows={3} placeholder="Run the test suite and summarize failures." />
        <div style={{ marginTop: 8 }}><button className="btn primary" onClick={save}>Save automation</button></div>
      </div>
      {items.map((a) => (
        <div className="card" key={a.id}>
          <div className="row"><strong>{a.name}</strong><span style={{ flex: 1 }} />
            <button className="btn primary" onClick={async () => {
              const r = await api.runAutomation(a.id);
              onRun(r.thread.id, r.prompt);
            }}>Run</button>
            <button className="btn" onClick={() => api.deleteAutomation(a.id).then(load)}>Delete</button></div>
          <div style={{ color: 'var(--muted)', fontSize: 12 }}>{a.prompt}</div>
        </div>
      ))}
      {items.length === 0 && <div style={{ color: 'var(--muted)' }}>No automations yet.</div>}
    </div>
  );
}
