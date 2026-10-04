import React, { useEffect, useState } from 'react';
import { api } from '../api/client';
import { I } from './Icon';
import { loadSettings, saveSettings, UISettings } from '../lib/settings';

const DEFAULT_URL: Record<string, string> = {
  local: 'http://localhost:8000/v1',
  ollama: 'http://localhost:11434/v1',
  lmstudio: 'http://localhost:1234/v1',
  custom: 'http://localhost:8000/v1',
  azure: 'https://<resource>.openai.azure.com',
};
const NEEDS_KEY = ['custom', 'openai', 'anthropic', 'gemini', 'openrouter', 'mistral', 'deepseek',
  'groq', 'together', 'fireworks', 'xai', 'cohere', 'azure', 'huggingface'];
const NEEDS_URL = ['local', 'ollama', 'lmstudio', 'custom', 'azure'];
const PROVIDERS = ['local', 'ollama', 'lmstudio', 'custom', 'openai', 'anthropic', 'gemini',
  'openrouter', 'mistral', 'deepseek', 'groq', 'together', 'fireworks', 'xai', 'cohere', 'azure', 'huggingface'];

type Tab = 'appearance' | 'agent' | 'providers' | 'shortcuts' | 'about';

export default function SettingsPanel({ onToast }: { onToast: (s: string) => void }) {
  const [tab, setTab] = useState<Tab>('appearance');
  const [ui, setUi] = useState<UISettings>(loadSettings());
  const [prov, setProv] = useState('local');
  const [key, setKey] = useState('');
  const [baseUrl, setBaseUrl] = useState(DEFAULT_URL.local);
  const [apiVersion, setApiVersion] = useState('2024-10-21');
  const [rt, setRt] = useState<any>(null);
  const [about, setAbout] = useState<any>(null);
  const [allProv, setAllProv] = useState<any[]>([]);

  useEffect(() => {
    api.runtimes().then(setRt).catch(() => {});
    api.about().then(setAbout).catch(() => {});
    api.providers().then((p) => setAllProv(p.providers || [])).catch(() => {});
  }, []);

  const set = (patch: Partial<UISettings>) => setUi(saveSettings(patch));

  const pick = (p: string) => {
    setProv(p);
    if (DEFAULT_URL[p]) setBaseUrl(DEFAULT_URL[p]);
  };

  const saveProvider = async () => {
    await api.configureProvider({
      provider: prov, apiKey: key || undefined,
      baseUrl: NEEDS_URL.includes(prov) ? baseUrl : undefined,
      apiVersion: prov === 'azure' ? apiVersion : undefined,
    });
    setKey('');
    window.dispatchEvent(new Event('mtrini:providers-changed'));
    onToast(`Provider ${prov} configured (key stored in OS keychain, never in config.json)`);
  };

  return (
    <div>
      <div className="row" style={{ gap: 4, marginBottom: 12 }}>
        {(['appearance', 'agent', 'providers', 'shortcuts', 'about'] as Tab[]).map((t) => (
          <button key={t} className={`btn ${tab === t ? 'primary' : ''}`} onClick={() => setTab(t)}>
            {t[0].toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {tab === 'appearance' && (
        <>
          <strong>Appearance</strong>
          <label className="f">Theme</label>
          <select className="t" value={ui.theme} onChange={(e) => set({ theme: e.target.value as any })}>
            <option value="glass">Liquid glass</option>
            <option value="dark">Dark</option>
            <option value="light">Light</option>
            <option value="system">System</option>
          </select>
          <label className="f">Accent</label>
          <div className="row">
            {(['teal', 'blue', 'green', 'violet', 'amber'] as const).map((a) => (
              <button key={a} title={a} onClick={() => set({ accent: a })}
                style={{ width: 26, height: 26, borderRadius: '50%', cursor: 'pointer',
                  background: { teal: '#0e9f7a', blue: '#4f8cff', green: '#34c98e', violet: '#8b7bff', amber: '#e5a63d' }[a],
                  border: ui.accent === a ? '2px solid var(--text)' : '2px solid transparent' }} />
            ))}
          </div>
          <label className="f">Density</label>
          <select className="t" value={ui.density} onChange={(e) => set({ density: e.target.value as any })}>
            <option value="comfortable">Comfortable</option>
            <option value="compact">Compact</option>
          </select>
          <label className="f">Editor font size ({ui.editorFontSize}px)</label>
          <input type="range" min={11} max={16} value={ui.editorFontSize}
            onChange={(e) => set({ editorFontSize: Number(e.target.value) })} style={{ width: '100%' }} />
          <div className="row" style={{ marginTop: 8 }}>
            <label className="row"><input type="checkbox" checked={ui.minimap} onChange={(e) => set({ minimap: e.target.checked })} /> Minimap</label>
            <label className="row"><input type="checkbox" checked={ui.wordWrap} onChange={(e) => set({ wordWrap: e.target.checked })} /> Word wrap</label>
          </div>
        </>
      )}

      {tab === 'agent' && (
        <>
          <strong>Agent & Terminal</strong>
          <label className="f">Default permission mode</label>
          <select className="t" value={ui.permissionMode} onChange={(e) => set({ permissionMode: e.target.value as any })}>
            <option value="ask">Ask — confirm every write, run and delete</option>
            <option value="auto">Auto — run without asking (your responsibility)</option>
            <option value="readonly">Read-only — agent can only inspect</option>
          </select>
          <p className="hint">Destructive operations always need approval unless Auto is selected.</p>
          <label className="f">Terminal font size ({ui.terminalFontSize}px)</label>
          <input type="range" min={10} max={16} value={ui.terminalFontSize}
            onChange={(e) => set({ terminalFontSize: Number(e.target.value) })} style={{ width: '100%' }} />
          <div style={{ marginTop: 10 }}>
            <strong>Runtime status</strong>
            <pre style={{ fontSize: 11 }}>{rt ? JSON.stringify(rt, null, 1) : '…'}</pre>
          </div>
        </>
      )}

      {tab === 'providers' && (
        <>
          <strong>Providers</strong>
          <label className="f">Provider</label>
          <select className="t" value={prov} onChange={(e) => pick(e.target.value)}>
            {(allProv.length ? allProv : PROVIDERS.map((id) => ({ id }))).map((p: any) => (
              <option key={p.id} value={p.id}>{p.label || p.id}{p.configured ? ' ●' : ''}</option>
            ))}
          </select>
          {NEEDS_KEY.includes(prov) && (
            <>
              <label className="f">API key{prov === 'huggingface' ? ' / token' : ''} (stored in OS keychain)</label>
              <input className="t" type="password" value={key} onChange={(e) => setKey(e.target.value)}
                placeholder={prov === 'azure' ? 'Azure API key' : 'sk-…'} autoComplete="off" />
            </>
          )}
          {NEEDS_URL.includes(prov) && (
            <>
              <label className="f">{prov === 'azure' ? 'Resource endpoint' : 'Base URL'}</label>
              <input className="t" value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} placeholder={DEFAULT_URL[prov] || 'https://…'} />
            </>
          )}
          {prov === 'azure' && (
            <>
              <label className="f">API version</label>
              <input className="t" value={apiVersion} onChange={(e) => setApiVersion(e.target.value)} />
              <p className="hint">Model field = your deployment name (used in the composer).</p>
            </>
          )}
          {prov === 'ollama' && <p className="hint">Install from ollama.com, then <code>ollama pull qwen2.5-coder</code>.</p>}
          {prov === 'lmstudio' && <p className="hint">LM Studio → Developer tab → Start Server (port 1234).</p>}
          <div style={{ marginTop: 8 }} className="row">
            <button className="btn primary" onClick={saveProvider}>Save provider</button>
            <button className="btn" onClick={() => api.disconnect(prov).then(() => { window.dispatchEvent(new Event('mtrini:providers-changed')); onToast('Disconnected'); })}>Disconnect</button>
          </div>
        </>
      )}

      {tab === 'shortcuts' && (
        <>
          <strong>Keyboard shortcuts</strong>
          <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 6 }}>
            {[['Ctrl/⌘ + K', 'Command menu'], ['Ctrl/⌘ + L', 'New thread'], ['Ctrl/⌘ + ,', 'Settings'],
              ['Enter', 'Send (Shift+Enter for newline)'], ['Esc', 'Close dialog / menu']].map(([k, v]) => (
              <div className="row" key={k}><kbd>{k}</kbd><span>{v}</span></div>
            ))}
          </div>
        </>
      )}

      {tab === 'about' && (
        <>
          <div className="row"><img src="/logo.png" alt="" width={36} height={36} />
            <div><strong>Mtrini Workspace</strong><br />
              <span style={{ color: 'var(--muted)', fontSize: 12 }}>Your AI. Your code. Your workspace.</span></div>
          </div>
          <pre style={{ fontSize: 12, marginTop: 10 }}>{about ? JSON.stringify(about, null, 1) : '…'}</pre>
          <p className="hint" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>{I.check()} No telemetry. Local-first. Apache-2.0.</p>
        </>
      )}
    </div>
  );
}
