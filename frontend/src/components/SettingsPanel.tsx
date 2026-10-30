import React, { useEffect, useState } from 'react';
import { api } from '../api/client';
import AccountPanel from './AccountPanel';
import { UpdateSettings } from './Updates';
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

const ACCENTS: Record<UISettings['accent'], string> = { teal: '#0e7490', blue: '#2563eb', green: '#15803d', violet: '#6d28d9', amber: '#a16207' };

type Tab = 'appearance' | 'chat' | 'agent' | 'providers' | 'account' | 'shortcuts' | 'about';
const TABS: { id: Tab; label: string }[] = [
  { id: 'appearance', label: 'Appearance' }, { id: 'chat', label: 'Chat' }, { id: 'agent', label: 'Agent' },
  { id: 'providers', label: 'Providers' }, { id: 'account', label: 'Account' }, { id: 'shortcuts', label: 'Shortcuts' },
  { id: 'about', label: 'About' },
];

function Row({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="setrow">
      <div><strong>{title}</strong>{hint && <p className="hint">{hint}</p>}</div>
      {children}
    </div>
  );
}

/** Your own OpenAI-compatible providers: add as many as you like (OrcaRouter, Kojo, a friend's server...). */
function CustomProviders({ providers, onToast, onChanged }: { providers: any[]; onToast: (s: string) => void; onChanged: () => void }) {
  const [label, setLabel] = useState('');
  const [url, setUrl] = useState('');
  const [key, setKey] = useState('');
  const custom = providers.filter((p) => p.custom);
  const add = async () => {
    try {
      const p = await api.addCustomProvider({ label: label.trim(), baseUrl: url.trim(), apiKey: key || undefined });
      setLabel(''); setUrl(''); setKey('');
      onChanged();
      onToast(`Added ${p.label}. Pick it in the composer.`);
    } catch (e: any) {
      const raw = String(e.message || e);
      const detail = /"detail"\s*:\s*"([^"]+)"/.exec(raw)?.[1];
      onToast(`Could not add provider: ${detail || raw}`);
    }
  };
  const remove = async (p: any) => {
    if (!confirm(`Remove ${p.label}? Its saved key is deleted too.`)) return;
    try { await api.deleteCustomProvider(p.id); onChanged(); onToast(`Removed ${p.label}`); } catch (e: any) { onToast(`Could not remove: ${e.message || e}`); }
  };
  return (
    <>
      <div className="label-caps" style={{ marginTop: 22 }}>Your own providers</div>
      <p className="hint">Any service with an OpenAI-compatible API: add as many as you like. Each gets its own name, address and key.</p>
      {custom.length > 0 && (
        <div className="customlist">
          {custom.map((p) => (
            <div key={p.id} className="setrow">
              <span><strong>{p.label}</strong> <span className="hint mono">{p.baseUrl}</span></span>
              <button className="btn" onClick={() => remove(p)} aria-label={`Remove ${p.label}`}>Remove</button>
            </div>
          ))}
        </div>
      )}
      <div className="customadd">
        <input className="t" aria-label="Provider name" placeholder="Name, e.g. OrcaRouter" value={label} onChange={(e) => setLabel(e.target.value)} />
        <input className="t" aria-label="Provider base URL" placeholder="Base URL, e.g. https://api.example.com/v1" value={url} onChange={(e) => setUrl(e.target.value)} />
        <input className="t" type="password" aria-label="Provider API key" placeholder="API key (optional)" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)} />
        <button className="btn primary" disabled={!label.trim() || !url.trim()} onClick={add}>Add provider</button>
      </div>
    </>
  );
}

/** Agent extras: web search provider and always-allow rules. */
function AgentExtras({ onToast }: { onToast: (s: string) => void }) {
  const [ws, setWs] = useState<{ provider: string; baseUrl: string; hasKey: boolean }>({ provider: '', baseUrl: '', hasKey: false });
  const [wsKey, setWsKey] = useState('');
  const [rules, setRules] = useState<string[]>([]);
  useEffect(() => {
    api.webSearch().then(setWs).catch(() => {});
    api.permissions().then((r) => setRules(r.allow || [])).catch(() => {});
  }, []);
  const saveWs = async () => {
    try {
      setWs(await api.saveWebSearch({ provider: ws.provider, baseUrl: ws.baseUrl, apiKey: wsKey || undefined }));
      setWsKey('');
      onToast('Web search saved');
    } catch (e: any) { onToast(`Could not save: ${e.message}`); }
  };
  const removeRule = async (r: string) => {
    try { setRules((await api.savePermissions(rules.filter((x) => x !== r))).allow); } catch (e: any) { onToast(`Could not save: ${e.message}`); }
  };
  return (
    <>
      <div className="label-caps" style={{ marginTop: 18 }}>Web search</div>
      <p className="hint">Lets the agent search the web. Pick a service and add its key (stored in your system keychain), or point it at your own SearXNG.</p>
      <Row title="Search service">
        <select className="t" aria-label="Search service" value={ws.provider} onChange={(e) => setWs({ ...ws, provider: e.target.value })}>
          <option value="">Off</option>
          <option value="brave">Brave Search API</option>
          <option value="tavily">Tavily</option>
          <option value="searxng">SearXNG (self-hosted)</option>
        </select>
      </Row>
      {(ws.provider === 'brave' || ws.provider === 'tavily') && (
        <Row title="API key" hint={ws.hasKey ? 'A key is saved. Type a new one to replace it.' : undefined}>
          <input className="t" type="password" aria-label="Search API key" value={wsKey} onChange={(e) => setWsKey(e.target.value)} placeholder={ws.hasKey ? '••••••••' : 'paste key'} />
        </Row>
      )}
      {ws.provider === 'searxng' && (
        <Row title="SearXNG URL">
          <input className="t" aria-label="SearXNG URL" value={ws.baseUrl} onChange={(e) => setWs({ ...ws, baseUrl: e.target.value })} placeholder="http://localhost:8888" />
        </Row>
      )}
      <button className="btn" onClick={saveWs}>Save web search</button>

      <div className="label-caps" style={{ marginTop: 18 }}>Always allowed</div>
      <p className="hint">Added with "Always allow" on an approval card; stored in this project's .mtrini/permissions.json. Commands the safety check marks destructive still ask.</p>
      {rules.length === 0 ? <p className="hint">Nothing yet.</p> : (
        <div className="chips">
          {rules.map((r) => (
            <span key={r} className="tag">{r} <button className="linkbtn" aria-label={`Remove ${r}`} onClick={() => removeRule(r)}>×</button></span>
          ))}
        </div>
      )}
    </>
  );
}

function Switch({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <label className="switch">
      <input type="checkbox" role="switch" aria-label={label} checked={checked} onChange={(e) => onChange(e.target.checked)} />
      <span />
    </label>
  );
}

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

  const loadProviders = () => api.providers().then((p) => setAllProv(p.providers || [])).catch(() => {});
  useEffect(() => {
    api.runtimes().then(setRt).catch(() => {});
    api.about().then(setAbout).catch(() => {});
    loadProviders();
  }, []);
  // Which fields a provider needs comes from the backend's list, so new providers get a key field automatically.
  const meta = allProv.find((p) => p.id === prov);
  const needKey = meta ? !!(meta.needsKey || meta.custom) : NEEDS_KEY.includes(prov);
  const needUrl = meta ? !!(meta.custom || (meta.fields || []).includes('baseUrl')) : NEEDS_URL.includes(prov);

  const set = (patch: Partial<UISettings>) => setUi(saveSettings(patch));

  const pick = (p: string) => {
    setProv(p);
    const m = allProv.find((x) => x.id === p);
    if (m?.custom) setBaseUrl(m.baseUrl || '');
    else if (DEFAULT_URL[p]) setBaseUrl(DEFAULT_URL[p]);
  };

  const saveProvider = async () => {
    try {
      await api.configureProvider({
        provider: prov, apiKey: key || undefined,
        baseUrl: needUrl ? baseUrl : undefined,
        apiVersion: prov === 'azure' ? apiVersion : undefined,
      });
      setKey('');
      loadProviders();
      window.dispatchEvent(new Event('mtrini:providers-changed'));
      onToast(`Provider ${meta?.label || prov} configured (key stored in OS keychain, never in config.json)`);
    } catch (e: any) { onToast(`Could not save provider: ${e.message || e}`); }
  };

  const reset = () => {
    if (!confirm('Reset all appearance, chat and agent settings to their defaults? Providers are not affected.')) return;
    localStorage.removeItem('mtrini.ui');
    setUi(saveSettings({}));
    onToast('Settings reset to defaults');
  };

  return (
    <div className="settings">
      <div className="settings-tabs" role="tablist" aria-label="Settings sections">
        {TABS.map((t) => (
          <button key={t.id} role="tab" aria-selected={tab === t.id} className={`btn ${tab === t.id ? 'primary' : ''}`} onClick={() => setTab(t.id)}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'appearance' && (
        <>
          <Row title="Theme">
            <select className="t" aria-label="Theme" value={ui.theme} onChange={(e) => set({ theme: e.target.value as UISettings['theme'] })}>
              <option value="light">Light</option>
              <option value="dark">Dark</option>
              <option value="system">Match system</option>
              <option value="glass">Liquid glass</option>
            </select>
          </Row>
          <Row title="Accent color">
            <div className="row">
              {(Object.keys(ACCENTS) as UISettings['accent'][]).map((a) => (
                <button key={a} title={a} aria-label={`${a} accent`} aria-pressed={ui.accent === a} onClick={() => set({ accent: a })}
                  style={{ width: 26, height: 26, borderRadius: '50%', cursor: 'pointer', background: ACCENTS[a],
                    border: ui.accent === a ? '2px solid var(--text)' : '2px solid transparent', outlineOffset: 2 }} />
              ))}
            </div>
          </Row>
          <Row title={`Text size (${ui.uiFontSize}px)`} hint="Size of text across the app.">
            <input type="range" min={12} max={18} value={ui.uiFontSize} aria-label="Text size"
              onChange={(e) => set({ uiFontSize: Number(e.target.value) })} />
          </Row>
          <Row title="Conversation width" hint="Wide uses more of large screens.">
            <select className="t" aria-label="Conversation width" value={ui.contentWidth} onChange={(e) => set({ contentWidth: e.target.value as UISettings['contentWidth'] })}>
              <option value="normal">Comfortable</option>
              <option value="wide">Wide</option>
            </select>
          </Row>
          <Row title="Density">
            <select className="t" aria-label="Density" value={ui.density} onChange={(e) => set({ density: e.target.value as UISettings['density'] })}>
              <option value="comfortable">Comfortable</option>
              <option value="compact">Compact</option>
            </select>
          </Row>
          <Row title="Motion" hint="Animations for spinners, menus and transitions.">
            <select className="t" aria-label="Motion" value={ui.motion} onChange={(e) => set({ motion: e.target.value as UISettings['motion'] })}>
              <option value="system">Follow system setting</option>
              <option value="reduce">Always reduce</option>
            </select>
          </Row>
          <Row title="Show changes panel on start" hint="The uncommitted-changes panel beside sessions.">
            <Switch label="Show changes panel on start" checked={ui.showChanges} onChange={(v) => set({ showChanges: v })} />
          </Row>
          <Row title={`Editor font size (${ui.editorFontSize}px)`}>
            <input type="range" min={11} max={18} value={ui.editorFontSize} aria-label="Editor font size"
              onChange={(e) => set({ editorFontSize: Number(e.target.value) })} />
          </Row>
          <Row title="Editor minimap"><Switch label="Editor minimap" checked={ui.minimap} onChange={(v) => set({ minimap: v })} /></Row>
          <Row title="Editor word wrap"><Switch label="Editor word wrap" checked={ui.wordWrap} onChange={(v) => set({ wordWrap: v })} /></Row>
        </>
      )}

      {tab === 'chat' && (
        <>
          <Row title="Send messages with" hint="The other combination inserts a new line.">
            <select className="t" aria-label="Send messages with" value={ui.sendKey} onChange={(e) => set({ sendKey: e.target.value as UISettings['sendKey'] })}>
              <option value="enter">Enter (Shift+Enter for new line)</option>
              <option value="mod-enter">Ctrl/⌘+Enter (Enter for new line)</option>
            </select>
          </Row>
          <Row title="Default thinking effort" hint="Used for each new session. Higher effort allows a deeper agent loop.">
            <select className="t" aria-label="Default thinking effort" value={ui.defaultEffort} onChange={(e) => set({ defaultEffort: e.target.value as UISettings['defaultEffort'] })}>
              {['off', 'low', 'medium', 'high', 'xhigh', 'max'].map((x) => <option key={x} value={x}>{x === 'off' ? 'Off' : x}</option>)}
            </select>
          </Row>
          <Row title="Expand tool output" hint="Show the output of every tool call without clicking.">
            <Switch label="Expand tool output" checked={ui.toolsExpanded} onChange={(v) => set({ toolsExpanded: v })} />
          </Row>
          <Row title="Starter suggestions" hint="Skills and example prompts on the empty session screen.">
            <Switch label="Starter suggestions" checked={ui.showStarters} onChange={(v) => set({ showStarters: v })} />
          </Row>
          <Row title="Confirm before deleting a session">
            <Switch label="Confirm before deleting a session" checked={ui.confirmDelete} onChange={(v) => set({ confirmDelete: v })} />
          </Row>
        </>
      )}

      {tab === 'agent' && (
        <>
          <Row title="Default permission mode" hint="Also switchable per message from the composer.">
            <select className="t" aria-label="Default permission mode" value={ui.permissionMode} onChange={(e) => set({ permissionMode: e.target.value as UISettings['permissionMode'] })}>
              <option value="ask">Ask before edits</option>
              <option value="auto">Auto-accept edits</option>
              <option value="readonly">Read-only</option>
              <option value="plan">Plan mode</option>
            </select>
          </Row>
          <p className="hint">Ask confirms every write, command and delete. Auto runs without asking, so use it only in projects you trust. Plan mode researches read-only and shows you a plan before changing anything.</p>
          <Row title="Use skills" hint="Give the agent your skill list, and a skill's full instructions when you type /name.">
            <Switch label="Use skills" checked={ui.useSkills} onChange={(v) => set({ useSkills: v })} />
          </Row>
          <Row title="Use project instructions" hint="Include .mtrini/instructions.md in every request.">
            <Switch label="Use project instructions" checked={ui.useInstructions} onChange={(v) => set({ useInstructions: v })} />
          </Row>
          <Row title={`Terminal font size (${ui.terminalFontSize}px)`}>
            <input type="range" min={10} max={18} value={ui.terminalFontSize} aria-label="Terminal font size"
              onChange={(e) => set({ terminalFontSize: Number(e.target.value) })} />
          </Row>
          <AgentExtras onToast={onToast} />
          <div style={{ marginTop: 16 }}>
            <div className="label-caps">Runtime status</div>
            <pre style={{ fontSize: 11 }}>{rt ? JSON.stringify(rt, null, 1) : '…'}</pre>
          </div>
        </>
      )}

      {tab === 'providers' && (
        <>
          <label className="f">Provider</label>
          <select className="t" value={prov} onChange={(e) => pick(e.target.value)}>
            {(allProv.length ? allProv.filter((p) => !p.free) : PROVIDERS.map((id) => ({ id }))).map((p: any) => (
              <option key={p.id} value={p.id}>{p.label || p.id}{p.configured ? ' ●' : ''}</option>
            ))}
          </select>
          {meta?.hint && <p className="hint">{meta.hint}</p>}
          {needKey && (
            <>
              <label className="f">API key{prov === 'huggingface' ? ' / token' : ''} (stored in OS keychain)</label>
              <input className="t" type="password" value={key} onChange={(e) => setKey(e.target.value)}
                placeholder={prov === 'azure' ? 'Azure API key' : 'sk-…'} autoComplete="off" />
            </>
          )}
          {needUrl && (
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
          <div style={{ marginTop: 12 }} className="row">
            <button className="btn primary" onClick={saveProvider}>Save provider</button>
            <button className="btn" onClick={() => api.disconnect(prov).then(() => { loadProviders(); window.dispatchEvent(new Event('mtrini:providers-changed')); onToast('Disconnected'); }).catch((e: any) => onToast(`Disconnect failed: ${e.message || e}`))}>Disconnect</button>
          </div>
          <CustomProviders providers={allProv} onToast={onToast}
            onChanged={() => { loadProviders(); window.dispatchEvent(new Event('mtrini:providers-changed')); }} />
        </>
      )}

      {tab === 'shortcuts' && (
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          {[['Ctrl/⌘ + K', 'Command menu'], ['Ctrl/⌘ + L', 'New session'], ['Ctrl/⌘ + ,', 'Settings'],
            ['/', 'Commands and skills (in the composer)'],
            [ui.sendKey === 'enter' ? 'Enter' : 'Ctrl/⌘ + Enter', 'Send message'],
            [ui.sendKey === 'enter' ? 'Shift + Enter' : 'Enter', 'New line'],
            ['↑ ↓  then Enter or Tab', 'Pick from the / menu'], ['Esc', 'Close dialog or menu']].map(([k, v]) => (
            <div className="setrow" key={k}><span>{v}</span><kbd>{k}</kbd></div>
          ))}
        </div>
      )}

      {tab === 'account' && <AccountPanel onToast={onToast} />}

      {tab === 'about' && (
        <>
          <div className="row"><img src="/logo.png" alt="" width={48} height={48} />
            <div><strong>Mtrini Workspace</strong><br />
              <span style={{ color: 'var(--muted)', fontSize: 12 }}>Your AI. Your code. Your workspace.</span></div>
          </div>
          <UpdateSettings />
          <pre style={{ fontSize: 12, marginTop: 10 }}>{about ? JSON.stringify(about, null, 1) : '…'}</pre>
          <p className="hint" style={{ display: 'flex', alignItems: 'center', gap: 6 }}>{I.check()} No telemetry. Local-first. Apache-2.0.</p>
          <div className="aboutby">
            <img className="logo-on-light" src="/brand/compiwer-wordmark-dark.png" alt="Compiwer AI" height={28} />
            <img className="logo-on-dark" src="/brand/compiwer-wordmark-light.png" alt="Compiwer AI" height={28} />
            <span>Built by Compiwer AI · Building AI For Everyone.</span>
          </div>
        </>
      )}

      {tab !== 'providers' && tab !== 'about' && tab !== 'shortcuts' && (
        <div style={{ marginTop: 22 }}><button className="btn" onClick={reset}>{I.refresh()} Reset to defaults</button></div>
      )}
    </div>
  );
}
