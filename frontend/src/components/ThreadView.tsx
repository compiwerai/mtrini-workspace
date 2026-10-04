import React, { useEffect, useRef, useState } from 'react';
import { api } from '../api/client';
import { I } from './Icon';

export type Msg = { role: 'user' | 'assistant' | 'tool'; text: string; kind?: string; ok?: boolean; ms?: number };

const FALLBACK_PROVIDERS = ['local', 'ollama', 'lmstudio', 'custom', 'openai', 'anthropic', 'gemini',
  'openrouter', 'mistral', 'deepseek', 'groq', 'together', 'fireworks', 'xai', 'cohere', 'azure', 'huggingface',
  'cerebras', 'deepinfra', 'nebius', 'sambanova', 'novita', 'siliconflow', 'sdwebui'];

function inline(text: string, key: string): React.ReactNode[] {
  const parts = text.split(/(`[^`]+`|\*\*[^*]+\*|\[[^\]]+\]\([^)]+\))/g);
  return parts.map((p, i) => {
    if (p.startsWith('`') && p.endsWith('`')) return <code key={key + i}>{p.slice(1, -1)}</code>;
    if (p.startsWith('**') && p.endsWith('**')) return <strong key={key + i}>{p.slice(2, -2)}</strong>;
    const m = p.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
    if (m) return <a key={key + i} onClick={() => window.dispatchEvent(new CustomEvent('mtrini:open', { detail: m[2] }))}>{m[1]}</a>;
    return <React.Fragment key={key + i}>{p}</React.Fragment>;
  });
}

function CodeBlock({ code }: { code: string }) {
  const [copied, setCopied] = useState(false);
  const first = code.split('\n')[0];
  const lang = /^[a-z+#-]{1,12}$/i.test(first.trim()) && !first.includes(' ') ? first.trim() : '';
  const body = lang ? code.split('\n').slice(1).join('\n') : code;
  const copy = async () => {
    try { await navigator.clipboard.writeText(body); } catch {
      const ta = document.createElement('textarea');
      ta.value = body; document.body.appendChild(ta); ta.select();
      document.execCommand('copy'); ta.remove();
    }
    setCopied(true);
    setTimeout(() => setCopied(false), 1200);
  };
  return (
    <div className="codeblock">
      <div className="cbhead"><span>{lang || 'code'}</span><button onClick={copy}>{copied ? 'Copied ✓' : 'Copy'}</button></div>
      <pre><code>{body}</code></pre>
    </div>
  );
}

function Body({ text }: { text: string }) {
  const out: React.ReactNode[] = [];
  const lines = text.split('\n');
  let i = 0, k = 0;
  while (i < lines.length) {
    const ln = lines[i];
    if (ln.startsWith('```')) {
      const buf: string[] = [];
      i++;
      while (i < lines.length && !lines[i].startsWith('```')) { buf.push(lines[i]); i++; }
      i++;
      out.push(<CodeBlock key={k++} code={buf.join('\n')} />);
      continue;
    }
    if (/^#{1,4}\s/.test(ln)) { out.push(<h4 key={k++}>{inline(ln.replace(/^#{1,4}\s/, ''), 'h' + k)}</h4>); i++; continue; }
    if (/^\s*[-•*]\s/.test(ln)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*[-•*]\s/.test(lines[i])) { items.push(lines[i].replace(/^\s*[-•*]\s/, '')); i++; }
      out.push(<ul key={k++}>{items.map((t, j) => <li key={j}>{inline(t, `li${k}${j}`)}</li>)}</ul>);
      continue;
    }
    if (/^\s*\d+[.)]\s/.test(ln)) {
      const items: string[] = [];
      while (i < lines.length && /^\s*\d+[.)]\s/.test(lines[i])) { items.push(lines[i].replace(/^\s*\d+[.)]\s/, '')); i++; }
      out.push(<ol key={k++}>{items.map((t, j) => <li key={j}>{inline(t, `ol${k}${j}`)}</li>)}</ol>);
      continue;
    }
    if (ln.trim() === '') { i++; continue; }
    out.push(<p key={k++}>{inline(ln, 'p' + k)}</p>);
    i++;
  }
  return <>{out}</>;
}

export default function ThreadView({ messages, busy, pending, files, branch, model, setModel, onSend, onStop, onApprove, onDeny, needsSetup, onGoSettings, threadWs, onPickThreadFolder, effort, setEffort }: {
  messages: Msg[]; busy: boolean; pending: { tool: string; args: any; mcp?: { server: string; tool: string } } | null;
  files: string[]; branch: string; model: string; setModel: (m: string) => void;
  onSend: (text: string) => void; onStop: () => void; onApprove: () => void; onDeny: () => void;
  needsSetup: boolean; onGoSettings: () => void;
  threadWs: string | null; onPickThreadFolder: () => void;
  effort: string; setEffort: (e: string) => void;
}) {
  const [input, setInput] = useState('');
  const [providers, setProviders] = useState<any[]>([]);
  const [prov, setProv] = useState('local');
  const [models, setModels] = useState<any[]>([]);
  const [mid, setMid] = useState('');
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => { api.providers().then((p) => setProviders(p.providers || [])).catch(() => {}); }, []);
  useEffect(() => {
    api.models(prov).then((m) => setModels(m.models || [])).catch(() => setModels([]));
    setModel(`${prov}:${mid}`);
  }, [prov]); // eslint-disable-line
  useEffect(() => { setModel(`${prov}:${mid}`); }, [mid]); // eslint-disable-line
  useEffect(() => { try { box.current?.scrollTo(0, 1e9); } catch { /* jsdom */ } }, [messages, pending]);

  const submit = () => { if (input.trim() && !busy) { onSend(input.trim()); setInput(''); } };

  return (
    <div className="thread">
      <div className="scroll" ref={box} aria-live="polite">
        {messages.length === 0 && (
          <div className="msg assistant">
            <div style={{ textAlign: 'center', padding: '26px 0 8px' }}>
              <img src="/logo.png" alt="Mtrini" width={44} height={44} className="herologo" />
              <h3 style={{ margin: '10px 0 4px' }}>Start a thread</h3>
              <p style={{ color: 'var(--muted)' }}>Ask for a change — the agent inspects the project, edits files, runs tests, and shows the diff on the right.</p>
            </div>
            {needsSetup && (
              <div className="card" style={{ borderColor: 'var(--accent)' }}>
                <strong>No provider configured yet.</strong>
                <p style={{ color: 'var(--muted)' }}>Point Mtrini at a local server (llama.cpp / Ollama) or add an API key to start.</p>
                <button className="btn primary" onClick={onGoSettings}>Open Settings → Providers</button>
              </div>
            )}
          </div>
        )}
        {messages.map((m, i) => (
          <div className="msg" key={i}>
            {m.role === 'user' ? (
              <div className="userpill"><span>{m.text}</span></div>
            ) : m.role === 'tool' ? (
              <details className="runblock" open={m.ok === false}>
                <summary>{m.ok === false ? I.x() : I.check()} {m.text}{m.ms != null ? ` · ${m.ms}ms` : ''}</summary>
                {m.kind && <pre>{m.kind}</pre>}
              </details>
            ) : (
              <div className="assistant"><Body text={m.text} /></div>
            )}
          </div>
        ))}
        {files.length > 0 && (
          <div className="msg">
            <h4 style={{ fontSize: 12, margin: '0 0 2px' }}>Files touched</h4>
            <div className="chips">
              {files.map((f) => (
                <button key={f} onClick={() => window.dispatchEvent(new CustomEvent('mtrini:open', { detail: f }))}>{f}</button>
              ))}
            </div>
          </div>
        )}
        {pending && (
          <div className="msg">
            <div className="card" role="alert" style={{ borderColor: 'var(--warn)' }}>
              <div>Agent wants to run{pending.mcp ? ` (MCP ${pending.mcp.server} → ${pending.mcp.tool})` : ''}:</div>
              <pre style={{ fontFamily: 'var(--mono)', fontSize: 12 }}>{pending.tool} {JSON.stringify(pending.args)}</pre>
              <div className="row">
                <button className="btn primary" onClick={onApprove}>Allow once</button>
                <button className="btn" onClick={onDeny}>Deny</button>
              </div>
            </div>
          </div>
        )}
      </div>
      <div className="composer">
        <div className={`box ${busy ? 'busy' : ''}`}>
          <textarea value={input} onChange={(e) => setInput(e.target.value)} placeholder="Ask for follow-up changes"
            aria-label="Thread input" rows={2}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); submit(); } }} />
          <div className="bar">
            <select className="pillselect" value={prov} onChange={(e) => setProv(e.target.value)} aria-label="Provider" data-testid="provider-select">
              {(providers.length ? providers : FALLBACK_PROVIDERS.map((id) => ({ id }))).map((p: any) => (
                <option key={p.id} value={p.id}>{p.label || p.id}{p.configured ? ' ●' : ''}</option>
              ))}
            </select>
            <input className="pillselect" value={mid} onChange={(e) => setMid(e.target.value)} list="mtrini-models" aria-label="Model" style={{ minWidth: 140 }} placeholder="model id" />
            <datalist id="mtrini-models">{models.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}</datalist>
            <select className={`pillselect${effort !== 'off' ? ' on' : ''}`} value={effort} onChange={(e) => setEffort(e.target.value)} aria-label="Thinking effort"
              title="Thinking effort: native reasoning on OpenAI / Anthropic / Gemini / Azure, plus a deeper agent loop (Low 12 → Max 60 steps).">
              {['off', 'low', 'medium', 'high', 'xhigh', 'max'].map((e) => (
                <option key={e} value={e}>{e === 'off' ? 'Think: off' : `Think: ${e}`}</option>
              ))}
            </select>
            {busy ? (
              <button className="sendbtn stop" onClick={onStop} aria-label="Stop">{I.stop()}</button>
            ) : (
              <button className={`sendbtn ${input.trim() ? 'ready' : ''}`} onClick={submit} disabled={!input.trim()} aria-label="Send">{I.send()}</button>
            )}
          </div>
        </div>
      </div>
      <div className="meta">
        <button className="metabtn" onClick={onPickThreadFolder} title="This chat's working folder">
          {I.folder()} {threadWs ? threadWs.split(/[/\\]/).filter(Boolean).pop() : 'default folder'}
        </button>
        <span className="right">{I.branch()} {branch}</span>
      </div>
    </div>
  );
}
