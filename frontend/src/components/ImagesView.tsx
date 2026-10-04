import React, { useEffect, useState } from 'react';
import { api, imgUrl } from '../api/client';

const SIZES = ['512x512', '768x768', '1024x1024', '1024x1536', '1536x1024'];

export default function ImagesView() {
  const [support, setSupport] = useState<Record<string, string>>({});
  const [providers, setProviders] = useState<any[]>([]);
  const [prov, setProv] = useState('openai');
  const [model, setModel] = useState('gpt-image-1');
  const [prompt, setPrompt] = useState('');
  const [size, setSize] = useState('1024x1024');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const [items, setItems] = useState<any[]>([]);
  const [view, setView] = useState<any | null>(null);

  const load = async () => {
    try { setSupport((await api.imagesSupport()).support || {}); } catch { /* ignore */ }
    try { setProviders((await api.providers()).providers || []); } catch { /* ignore */ }
    try { setItems((await api.imagesList()).images || []); } catch { setItems([]); }
  };
  useEffect(() => { load(); }, []);

  const cap = support[prov] || 'no';
  const gen = async () => {
    if (!prompt.trim() || busy) return;
    setBusy(true);
    setErr('');
    try {
      const e = await api.generateImage(prov, model.trim(), prompt.trim(), size);
      setItems((items) => [e, ...items]);
      setPrompt('');
    } catch (e: any) { setErr(String(e.message || e).slice(0, 400)); }
    finally { setBusy(false); }
  };

  return (
    <div className="view">
      <h2>Mtrini Images</h2>
      <p style={{ color: 'var(--muted)' }}>Generate pictures with image models from any provider. Files are saved per working folder.</p>
      <div className="card">
        <label className="f">Prompt</label>
        <textarea className="t" rows={2} value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="A glass lighthouse on a mint sea, soft morning light…" />
        <div className="row" style={{ marginTop: 8, flexWrap: 'wrap' }}>
          <select className="pillselect" value={prov} onChange={(e) => setProv(e.target.value)} aria-label="Image provider">
            {(providers.length ? providers : [{ id: 'openai' }]).map((p: any) => (
              <option key={p.id} value={p.id}>
                {p.id}{support[p.id] === 'yes' ? ' ●' : support[p.id] === 'maybe' ? ' ◐' : support[p.id] === 'no' ? ' ○' : ''}
              </option>
            ))}
          </select>
          <input className="pillselect" value={model} onChange={(e) => setModel(e.target.value)} aria-label="Image model" placeholder="model id" style={{ minWidth: 150 }} />
          <select className="pillselect" value={size} onChange={(e) => setSize(e.target.value)} aria-label="Size">
            {SIZES.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
          <button className="btn primary" onClick={gen} disabled={busy || !prompt.trim()}>{busy ? 'Dreaming…' : 'Generate'}</button>
        </div>
        {cap === 'no' && <p className="hint">This provider has no image backend — pick one marked ●.</p>}
        {cap === 'maybe' && <p className="hint">Local servers vary: Mtrini tries OpenAI-shape, then SD WebUI-shape.</p>}
        {err && <p style={{ color: 'var(--danger)' }}>{err}</p>}
      </div>
      <div className="grid">
        {items.map((it) => (
          <div className="shot" key={it.id}>
            <img src={imgUrl(it.id)} alt={it.prompt} loading="lazy" onClick={() => setView(it)} />
            <footer>
              <span title={it.prompt}>{it.prompt.slice(0, 60)}</span>
              <button title="Delete" onClick={() => api.deleteImage(it.id).then(load)}>✕</button>
            </footer>
          </div>
        ))}
      </div>
      {items.length === 0 && <div style={{ color: 'var(--muted)' }}>No images yet — describe one above.</div>}
      {view && (
        <div className="modal" onClick={() => setView(null)} role="dialog" aria-label="Image viewer">
          <div className="sheet" style={{ width: 640 }} onClick={(e) => e.stopPropagation()}>
            <img src={imgUrl(view.id)} alt={view.prompt} style={{ width: '100%', borderRadius: 10 }} />
            <p style={{ fontSize: 12, color: 'var(--muted)' }}>{view.prompt} · {view.provider}/{view.model} · {view.size}</p>
            <div className="row">
              <a className="btn primary" href={imgUrl(view.id)} download={`${view.id}.png`}>Download</a>
              <button className="btn" onClick={() => setView(null)}>Close</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
