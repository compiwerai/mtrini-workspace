import React, { useEffect, useMemo, useRef, useState } from 'react';
import { api, type Skill } from '../api/client';
import { loadSettings, saveSettings, type UISettings } from '../lib/settings';
import { I } from './Icon';

export type ToolStatus = 'running' | 'ok' | 'error';
export type Msg = {
  role: 'user' | 'assistant' | 'tool' | 'note' | 'plan';
  text: string;
  /** Tool call id (matches results to their call). */
  id?: string;
  /** Set on tool rows run by a subagent: the id of the `task` call. */
  parent?: string;
  /** Unified diff lines for file edits. */
  diff?: string[];
  /** User turn number (rewind target). */
  turn?: number;
  images?: number;
  /** Legacy tool detail text. */
  kind?: string;
  ok?: boolean;
  ms?: number;
  tool?: string;
  args?: any;
  status?: ToolStatus;
  output?: string;
};

/** Built-in slash commands, handled in the app (not sent to the model). */
export const BUILTIN_COMMANDS: { name: string; description: string }[] = [
  { name: 'help', description: 'Show commands and skills' },
  { name: 'clear', description: 'Start a new session' },
  { name: 'skills', description: 'Open the skills manager' },
  { name: 'mcp', description: 'Manage MCP servers' },
  { name: 'settings', description: 'Open settings' },
  { name: 'compact', description: 'Summarize earlier conversation to free up context' },
  { name: 'init', description: 'Write .mtrini/instructions.md for this project' },
  { name: 'agents', description: 'List this project\'s subagents (.mtrini/agents)' },
  { name: 'permissions', description: 'Show tools and commands that are always allowed' },
];

export type Todo = { content: string; status: 'pending' | 'in_progress' | 'completed' };
export type Img = { mime: string; data: string; name: string };
export type PlanDecision = { decision: 'approve' | 'reject'; mode?: 'ask' | 'auto'; feedback?: string };

const CUSTOM = '__custom';

/** The last provider and model you chatted with, kept across restarts. */
function savedChoice(): { prov: string; mid: string } {
  try {
    const v = JSON.parse(localStorage.getItem('mtrini.chatModel') || '{}');
    return { prov: String(v.prov || ''), mid: String(v.mid || '') };
  } catch { return { prov: '', mid: '' }; }
}

const MODES: { id: UISettings['permissionMode']; label: string }[] = [
  { id: 'ask', label: 'Ask before edits' },
  { id: 'auto', label: 'Auto-accept edits' },
  { id: 'readonly', label: 'Read-only' },
  { id: 'plan', label: 'Plan mode' },
];

const VERBS: Record<string, string> = {
  read_file: 'Read', write_file: 'Write', edit_file: 'Edit', delete_file: 'Delete', move_file: 'Move',
  list_directory: 'List', file_exists: 'Check', search_code: 'Search', search_filename: 'Find',
  execute_command: 'Run', run_python: 'Python', inspect_project: 'Inspect project',
  detect_language: 'Detect language', detect_package_manager: 'Detect package manager',
  git_status: 'Git status', git_diff: 'Git diff', git_log: 'Git log', git_branch: 'Git branch', git_show: 'Git show',
  web_fetch: 'Fetch', web_search: 'Web search', task: 'Subagent',
};

export function toolLabel(tool = '', args: any = {}): { verb: string; target: string } {
  const verb = VERBS[tool] || tool.replace(/_/g, ' ').replace(/^\w/, (c) => c.toUpperCase());
  const a = args || {};
  const raw = a.command ?? a.path ?? a.query ?? a.url ?? a.pattern ?? a.src ?? a.description ?? a.code ?? '';
  const target = typeof raw === 'string' ? raw : JSON.stringify(raw);
  const extra = a.dst ? ` → ${a.dst}` : '';
  return { verb, target: (target + extra).replace(/\s+/g, ' ').slice(0, 120) };
}

function inline(text: string, key: string): React.ReactNode[] {
  const parts = text.split(/(`[^`]+`|\*\*[^*]+\*\*|\[[^\]]+\]\([^)]+\))/g);
  return parts.map((p, i) => {
    if (p.startsWith('`') && p.endsWith('`') && p.length > 1) return <code key={key + i}>{p.slice(1, -1)}</code>;
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
      <div className="cbhead"><span>{lang || 'code'}</span><button onClick={copy}>{copied ? 'Copied' : 'Copy'}</button></div>
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

function ToolRow({ m, expanded }: { m: Msg; expanded: boolean }) {
  if (!m.tool) {
    // Older thread entries without structured tool data.
    return (
      <details className={`toolrow ${m.ok === false ? 'error' : 'ok'}`}>
        <summary><span className="tdot" aria-hidden="true" /><span className="ttarget">{m.text}</span></summary>
        {m.kind && <pre>{m.kind}</pre>}
      </details>
    );
  }
  const { verb, target } = toolLabel(m.tool, m.args);
  const status = m.status || 'ok';
  const diff = m.diff && m.diff.length ? m.diff : null;
  return (
    <details className={`toolrow ${status}${m.parent ? ' sub' : ''}`} open={status === 'error' || (expanded && !!(m.output || diff))}>
      <summary>
        <span className="tdot" aria-hidden="true" />
        <b>{verb}</b>
        {target && <span className="ttarget">{target}</span>}
        <span className="tmeta">
          {status === 'running' ? 'running…' : status === 'error' ? 'failed' : m.ms != null ? `${m.ms} ms` : ''}
        </span>
      </summary>
      {diff ? <DiffLines lines={diff} /> : m.output && <pre>{m.output}</pre>}
    </details>
  );
}

function DiffLines({ lines }: { lines: string[] }) {
  const body = lines.filter((l) => !l.startsWith('---') && !l.startsWith('+++'));
  return (
    <pre className="difflines difftext" aria-label="Changes">
      {body.map((l, i) => (
        <span key={i} className={l.startsWith('@@') ? 'hunk' : l.startsWith('+') ? 'add' : l.startsWith('-') ? 'del' : ''}>{l}{'\n'}</span>
      ))}
    </pre>
  );
}

function TodoList({ todos }: { todos: Todo[] }) {
  const [open, setOpen] = useState(true);
  const done = todos.filter((t) => t.status === 'completed').length;
  return (
    <div className="todos" aria-label="Agent task list">
      <button className="todohead" onClick={() => setOpen((v) => !v)} aria-expanded={open}>
        Tasks <span className="hint">{done}/{todos.length}</span>
      </button>
      {open && (
        <ul>
          {todos.map((t, i) => (
            <li key={i} className={t.status}>
              <span className="tbox" aria-hidden="true">{t.status === 'completed' ? '✓' : t.status === 'in_progress' ? '•' : ''}</span>
              <span>{t.content}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function PlanCard({ plan, onPlan }: { plan: string; onPlan: (d: PlanDecision) => void }) {
  const [feedback, setFeedback] = useState('');
  return (
    <div className="permcard plancard" role="alert">
      <div className="permhead">Mtrini's plan</div>
      <div className="planbody"><Body text={plan} /></div>
      <div className="row">
        <button className="btn primary" onClick={() => onPlan({ decision: 'approve', mode: 'auto' })}>Approve, auto-accept edits</button>
        <button className="btn" onClick={() => onPlan({ decision: 'approve', mode: 'ask' })}>Approve, ask before edits</button>
      </div>
      <div className="row" style={{ marginTop: 8 }}>
        <input className="t" style={{ flex: 1 }} value={feedback} onChange={(e) => setFeedback(e.target.value)}
          placeholder="Or tell Mtrini what to change" aria-label="Plan feedback"
          onKeyDown={(e) => { if (e.key === 'Enter' && feedback.trim()) onPlan({ decision: 'reject', feedback }); }} />
        <button className="btn" disabled={!feedback.trim()} onClick={() => onPlan({ decision: 'reject', feedback })}>Keep planning</button>
      </div>
    </div>
  );
}

function readImage(f: File): Promise<Img | null> {
  if (!f.type.startsWith('image/') || f.size > 8 * 1024 * 1024) return Promise.resolve(null);
  return new Promise((res) => {
    const r = new FileReader();
    r.onload = () => res({ mime: f.type, data: String(r.result).split(',')[1] || '', name: f.name || 'image' });
    r.onerror = () => res(null);
    r.readAsDataURL(f);
  });
}

type Pending = { tool: string; args: any; rule?: string; mcp?: { server: string; tool: string } } | null;

export default function ThreadView({ messages, busy, status, pending, files, branch, setModel, onSend, onCommand, onStop, onApprove, onDeny,
  needsSetup, onGoSettings, threadWs, onPickThreadFolder, effort, setEffort, project, seed,
  todos = [], plan = null, onPlan = () => {}, hooksUntrusted = false, onTrustHooks = () => {}, onRewind,
  onReasoning = () => {} }: {
  messages: Msg[]; busy: boolean; status: string; pending: Pending;
  files: string[]; branch: string; model: string; setModel: (m: string) => void;
  onSend: (text: string, images?: Img[]) => void; onCommand: (name: string) => void;
  onStop: () => void; onApprove: (always?: boolean) => void; onDeny: () => void;
  todos?: Todo[]; plan?: string | null; onPlan?: (d: PlanDecision) => void;
  hooksUntrusted?: boolean; onTrustHooks?: () => void; onRewind?: (turn: number) => void;
  /** Whether the selected model takes a thinking level (the effort picker only shows then). */
  onReasoning?: (supported: boolean) => void;
  needsSetup: boolean; onGoSettings: () => void;
  threadWs: string | null; onPickThreadFolder: () => void;
  effort: string; setEffort: (e: string) => void;
  project: string; seed: { text: string; n: number } | null;
}) {
  const [input, setInput] = useState('');
  const [providers, setProviders] = useState<any[]>([]);
  const [prov, setProv] = useState(() => savedChoice().prov);
  const [models, setModels] = useState<any[]>([]);
  const [mid, setMid] = useState(() => savedChoice().mid);
  const [customModel, setCustomModel] = useState(false);
  const [skills, setSkills] = useState<Skill[]>([]);
  const [menuIndex, setMenuIndex] = useState(0);
  const [mode, setMode] = useState<UISettings['permissionMode']>(loadSettings().permissionMode);
  const [ui, setUi] = useState<UISettings>(loadSettings());
  const [images, setImages] = useState<Img[]>([]);
  const box = useRef<HTMLDivElement>(null);
  const ta = useRef<HTMLTextAreaElement>(null);

  // Only providers you connected (a saved key, or a local server you set up) can be picked to chat.
  const chatProviders = useMemo(() => providers.filter((p) => p.configured && p.kind !== 'image'), [providers]);
  useEffect(() => {
    const load = () => api.providers().then((p) => setProviders(p.providers || [])).catch(() => {});
    load();
    window.addEventListener('mtrini:providers-changed', load);
    return () => window.removeEventListener('mtrini:providers-changed', load);
  }, []);
  useEffect(() => {
    // The saved provider was disconnected (or nothing is saved yet): fall back to the first connected one.
    if (!providers.length || chatProviders.some((p) => p.id === prov)) return;
    const next = chatProviders[0];
    setProv(next?.id || '');
    setMid(next?.defaultModel || '');
    setCustomModel(false);
  }, [chatProviders]); // eslint-disable-line
  useEffect(() => { api.skills().then((s) => setSkills(s.skills || [])).catch(() => {}); }, []);
  useEffect(() => {
    if (!prov) { setModels([]); return; }
    let live = true;
    api.models(prov).then((m) => {
      if (!live) return;
      const list = m.models || [];
      setModels(list);
      if (!mid && list.length) setMid(list[0].id);
      else if (mid && !list.some((x: any) => x.id === mid)) setCustomModel(true);
      else if (!list.length) setCustomModel(true);
    }).catch(() => { if (live) { setModels([]); setCustomModel(true); } });
    return () => { live = false; };
  }, [prov]); // eslint-disable-line
  useEffect(() => {
    setModel(`${prov}:${mid}`);
    if (prov) { try { localStorage.setItem('mtrini.chatModel', JSON.stringify({ prov, mid })); } catch { /* private mode */ } }
  }, [prov, mid]); // eslint-disable-line
  const current = models.find((m) => m.id === mid);
  const reasoning = !!current?.capabilities?.reasoning;
  useEffect(() => { onReasoning(reasoning); }, [reasoning]); // eslint-disable-line
  const pickProvider = (id: string) => {
    setProv(id);
    setMid(chatProviders.find((p) => p.id === id)?.defaultModel || '');
    setCustomModel(false);
  };
  useEffect(() => { try { box.current?.scrollTo(0, 1e9); } catch { /* jsdom */ } }, [messages, pending, status, plan]);
  useEffect(() => {
    // The plan card can switch the mode (approve → auto/ask): follow the app's setting.
    setMode(loadSettings().permissionMode);
  }, [plan]);
  useEffect(() => {
    if (!seed) return;
    setInput(seed.text);
    requestAnimationFrame(() => { ta.current?.focus(); ta.current?.setSelectionRange(seed.text.length, seed.text.length); });
  }, [seed]);
  useEffect(() => {
    const h = () => { const s = loadSettings(); setMode(s.permissionMode); setUi(s); };
    window.addEventListener('mtrini:ui-changed', h);
    return () => window.removeEventListener('mtrini:ui-changed', h);
  }, []);

  // Slash menu: open while the first token is "/partial" with no space yet.
  const slash = /^\/([a-z0-9-]*)$/.exec(input);
  const menu = useMemo(() => {
    if (!slash) return [];
    const q = slash[1];
    const items = [
      ...BUILTIN_COMMANDS.map((c) => ({ ...c, kind: 'command' as const })),
      ...skills.map((s) => ({ name: s.name, description: s.description, kind: 'skill' as const })),
    ];
    return items.filter((i) => i.name.startsWith(q)).slice(0, 10);
  }, [slash?.[1], skills]); // eslint-disable-line
  useEffect(() => { setMenuIndex(0); }, [menu.length]);

  const pick = (item: { name: string; kind: 'command' | 'skill' }) => {
    if (item.kind === 'command') { setInput(''); onCommand(item.name); return; }
    setInput(`/${item.name} `);
    ta.current?.focus();
  };

  const submit = () => {
    const text = input.trim();
    if (!text || busy) return;
    const cmd = /^\/([a-z0-9-]+)$/.exec(text);
    if (cmd && BUILTIN_COMMANDS.some((c) => c.name === cmd[1])) { setInput(''); onCommand(cmd[1]); return; }
    onSend(text, images.length ? images : undefined);
    setInput('');
    setImages([]);
  };

  const addFiles = async (list: FileList | File[]) => {
    const got = (await Promise.all(Array.from(list).map(readImage))).filter(Boolean) as Img[];
    if (got.length) setImages((cur) => [...cur, ...got].slice(0, 8));
  };
  const onPaste = (e: React.ClipboardEvent) => {
    const fs = Array.from(e.clipboardData?.files || []).filter((f) => f.type.startsWith('image/'));
    if (fs.length) { e.preventDefault(); addFiles(fs); }
  };
  const onDrop = (e: React.DragEvent) => {
    if (e.dataTransfer?.files?.length) { e.preventDefault(); addFiles(e.dataTransfer.files); }
  };

  const onKey = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (menu.length) {
      if (e.key === 'ArrowDown') { e.preventDefault(); setMenuIndex((i) => (i + 1) % menu.length); return; }
      if (e.key === 'ArrowUp') { e.preventDefault(); setMenuIndex((i) => (i - 1 + menu.length) % menu.length); return; }
      if (e.key === 'Tab' || (e.key === 'Enter' && !e.shiftKey)) { e.preventDefault(); pick(menu[menuIndex]); return; }
      if (e.key === 'Escape') { e.preventDefault(); setInput(input + ' '); return; }
    }
    if (e.key === 'Enter' && !e.shiftKey) {
      const mod = e.ctrlKey || e.metaKey;
      if (ui.sendKey === 'enter' || mod) { e.preventDefault(); submit(); }
    }
  };

  const setPermission = (m: UISettings['permissionMode']) => { setMode(m); saveSettings({ permissionMode: m }); };
  const empty = messages.length === 0;
  const pendingLabel = pending ? toolLabel(pending.tool, pending.args) : null;

  return (
    <div className="thread">
      <div className="scroll" ref={box} aria-live="polite">
        {empty && (
          <div className="msg hero">
            <img src="/logo.png" alt="" width={44} height={44} className="herologo" />
            <h1>What should we build{project ? ` in ${project}` : ''}?</h1>
            <p className="hint">The agent inspects your project, edits files, runs tests and shows every change. Type <code>/</code> for commands and skills.</p>
            {prov === 'free' && (
              <p className="hint freenote">
                You're on the free model: Qwen3.8 27B, sponsored by <a href="https://heabsy.com" target="_blank" rel="noreferrer">Heabsy</a>.
                It has a daily limit; connect any provider in <a onClick={onGoSettings}>Settings</a> for more.
              </p>
            )}
            {needsSetup ? (
              <div className="card setup">
                <strong>Connect a model to start</strong>
                <p className="hint">Point Mtrini at a local server (llama.cpp, Ollama, LM Studio) or add an API key.</p>
                <button className="btn primary" onClick={onGoSettings}>Open Settings → Providers</button>
              </div>
            ) : ui.showStarters && (
              <div className="starters">
                {skills.slice(0, 3).map((s) => (
                  <button key={s.scope + s.name} className="starter" onClick={() => { setInput(`/${s.name} `); ta.current?.focus(); }}>
                    <span className="mono">/{s.name}</span><span>{s.description}</span>
                  </button>
                ))}
                {['Explain how this project is structured', 'Find and fix a failing test'].slice(0, Math.max(1, 4 - Math.min(skills.length, 3))).map((p) => (
                  <button key={p} className="starter" onClick={() => { setInput(p); ta.current?.focus(); }}>
                    <span>{p}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
        )}

        {hooksUntrusted && (
          <div className="msg">
            <div className="permcard" role="alert">
              <div className="permhead">This project has hooks</div>
              <p className="hint">.mtrini/hooks.json runs shell commands when the agent works. They stay off until you trust this exact file. Read it first.</p>
              <div className="row">
                <button className="btn" onClick={() => window.dispatchEvent(new CustomEvent('mtrini:open', { detail: '.mtrini/hooks.json' }))}>Open hooks.json</button>
                <button className="btn primary" onClick={onTrustHooks}>Trust these hooks</button>
              </div>
            </div>
          </div>
        )}

        {messages.map((m, i) => (
          <div className={`msg ${m.role}`} key={i}>
            {m.role === 'user' ? (
              <div className="userpill">
                <span>{m.text}{m.images ? <em className="hint"> · {m.images} image{m.images > 1 ? 's' : ''}</em> : null}</span>
                {onRewind && m.turn && !busy ? (
                  <button className="rewind" title="Rewind: undo the agent's file changes and conversation from this message on"
                    aria-label="Rewind to before this message" onClick={() => onRewind(m.turn as number)}>↺</button>
                ) : null}
              </div>
            ) : m.role === 'plan' ? (
              <div className="note"><div className="label-caps">Plan</div><Body text={m.text} /></div>
            ) : m.role === 'tool' ? (
              <ToolRow m={m} expanded={ui.toolsExpanded} />
            ) : m.role === 'note' ? (
              <div className="note"><Body text={m.text} /></div>
            ) : (
              <div className="assistant"><Body text={m.text} /></div>
            )}
          </div>
        ))}

        {plan && !busy && <div className="msg"><PlanCard plan={plan} onPlan={onPlan} /></div>}

        {busy && !pending && (
          <div className="msg"><div className="livestatus"><span className="spark" aria-hidden="true" />{status || 'Working…'}</div></div>
        )}

        {files.length > 0 && (
          <div className="msg">
            <div className="label-caps">Files changed</div>
            <div className="chips">
              {files.map((f) => (
                <button key={f} onClick={() => window.dispatchEvent(new CustomEvent('mtrini:open', { detail: f }))}>{f}</button>
              ))}
            </div>
          </div>
        )}

        {pending && pendingLabel && (
          <div className="msg">
            <div className="permcard" role="alert">
              <div className="permhead">
                Allow Mtrini to <b>{pendingLabel.verb.toLowerCase()}</b>{pending.mcp ? ` with MCP ${pending.mcp.server} → ${pending.mcp.tool}` : ''}?
              </div>
              <pre>{pendingLabel.target || JSON.stringify(pending.args, null, 1)}</pre>
              <div className="row">
                <button className="btn primary" onClick={() => onApprove(false)}>Allow once</button>
                {pending.rule && (
                  <button className="btn" onClick={() => onApprove(true)} title="Saved in .mtrini/permissions.json">
                    Always allow <code>{pending.rule.replace(/^execute_command:/, '')}</code>
                  </button>
                )}
                <button className="btn" onClick={onDeny}>Deny</button>
                <span className="hint" style={{ marginLeft: 'auto' }}>Mode: {MODES.find((x) => x.id === mode)?.label}</span>
              </div>
            </div>
          </div>
        )}
      </div>

      <div className="composer">
        {todos.length > 0 && <TodoList todos={todos} />}
        {menu.length > 0 && (
          <div className="slashmenu" role="listbox" aria-label="Commands and skills">
            {menu.map((item, i) => (
              <button key={item.kind + item.name} role="option" aria-selected={i === menuIndex}
                className={i === menuIndex ? 'on' : ''} onMouseEnter={() => setMenuIndex(i)} onClick={() => pick(item)}>
                <span className="mono">/{item.name}</span>
                <span className="sdesc">{item.description}</span>
                <span className="skind">{item.kind}</span>
              </button>
            ))}
          </div>
        )}
        <div className={`box ${busy ? 'busy' : ''}`} onDrop={onDrop} onDragOver={(e) => e.preventDefault()}>
          {images.length > 0 && (
            <div className="thumbs" aria-label="Attached images">
              {images.map((im, i) => (
                <span key={i} className="thumb">
                  <img src={`data:${im.mime};base64,${im.data}`} alt={im.name} />
                  <button aria-label={`Remove ${im.name}`} onClick={() => setImages((cur) => cur.filter((_, j) => j !== i))}>×</button>
                </span>
              ))}
            </div>
          )}
          <textarea ref={ta} value={input} onChange={(e) => setInput(e.target.value)} onPaste={onPaste}
            placeholder={empty ? 'Describe a change, or type / for skills' : 'Reply, or ask for follow-up changes'}
            aria-label="Message the agent" rows={2} onKeyDown={onKey} />
          <div className="bar">
            <select className={`pillselect mode mode-${mode}`} value={mode} onChange={(e) => setPermission(e.target.value as UISettings['permissionMode'])} aria-label="Permission mode">
              {MODES.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
            </select>
            <span className="grow" />
            {chatProviders.length === 0 ? (
              <button className="pillselect" onClick={onGoSettings} title="Add an API key or a local server in Settings → Providers">Connect a provider</button>
            ) : (
              <>
                <select className="pillselect" value={prov} onChange={(e) => pickProvider(e.target.value)} aria-label="Provider" data-testid="provider-select">
                  {chatProviders.map((p: any) => <option key={p.id} value={p.id}>{p.label || p.id}</option>)}
                </select>
                <select className="pillselect" aria-label="Model" style={{ maxWidth: 200 }}
                  value={customModel || !current ? CUSTOM : mid}
                  onChange={(e) => {
                    if (e.target.value === CUSTOM) { setCustomModel(true); return; }
                    setCustomModel(false);
                    setMid(e.target.value);
                  }}>
                  {models.map((m) => <option key={m.id} value={m.id}>{m.label || m.id}</option>)}
                  <option value={CUSTOM}>Other model id…</option>
                </select>
                {(customModel || !current) && (
                  <input className="pillselect" value={mid} onChange={(e) => setMid(e.target.value.trim())} aria-label="Model id"
                    style={{ minWidth: 130 }} placeholder="model id" />
                )}
              </>
            )}
            {reasoning && (
              <select className={`pillselect${effort !== 'off' ? ' on' : ''}`} value={effort} onChange={(e) => setEffort(e.target.value)} aria-label="Thinking effort"
                title="How long the model thinks before answering. Higher levels are slower and cost more, and give the agent more steps (Low 12 → Max 60).">
                {['off', 'low', 'medium', 'high', 'xhigh', 'max'].map((e) => (
                  <option key={e} value={e}>{e === 'off' ? 'Think: off' : `Think: ${e}`}</option>
                ))}
              </select>
            )}
            {busy ? (
              <button className="sendbtn stop" onClick={onStop} aria-label="Stop">{I.stop()}</button>
            ) : (
              <button className={`sendbtn ${input.trim() ? 'ready' : ''}`} onClick={submit} disabled={!input.trim()} aria-label="Send">{I.send()}</button>
            )}
          </div>
        </div>
      </div>
      <div className="meta">
        <button className="metabtn" onClick={onPickThreadFolder} title="This session's working folder">
          {I.folder()} {threadWs ? threadWs.split(/[/\\]/).filter(Boolean).pop() : project || 'default folder'}
        </button>
        <span className="right">{I.branch()} {branch}</span>
      </div>
    </div>
  );
}
