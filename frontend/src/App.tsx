import React, { useCallback, useEffect, useRef, useState } from 'react';
import { api, getWorkspace, setExecOverride, setWorkspace, sse, touchRecent } from './api/client';
import CommandMenu, { ActionId } from './components/CommandMenu';
import { applySettings, loadSettings, saveSettings } from './lib/settings';
import DiffPanel from './components/DiffPanel';
import FilesView from './components/FilesView';
import ImagesView from './components/ImagesView';
import MCPView from './components/MCPView';
import { AutomationsView } from './components/Panels';
import SkillsView from './components/SkillsView';
import SettingsPanel from './components/SettingsPanel';
import Sidebar, { Nav } from './components/Sidebar';
import ThreadView, { BUILTIN_COMMANDS, Img, Msg, PlanDecision, Todo } from './components/ThreadView';
import TopBar from './components/TopBar';
import WorkspacePicker from './components/WorkspacePicker';

/** Human-readable tool output: command results as their actual text, file reads as content. */
export function formatToolOutput(v: any): string {
  if (v == null) return '';
  if (typeof v === 'string') return v.replace(/\r\n/g, '\n').slice(0, 4000);
  if (typeof v === 'object' && ('stdout' in v || 'stderr' in v || 'exitCode' in v)) {
    const parts = [String(v.stdout || '').trimEnd(), String(v.stderr || '').trimEnd()].filter(Boolean);
    const body = parts.join('\n').replace(/\r\n/g, '\n');
    return `${body}${body ? '\n' : ''}exit code ${v.exitCode ?? '?'}`.slice(0, 4000);
  }
  if (typeof v === 'object' && typeof v.content === 'string') return v.content.replace(/\r\n/g, '\n').slice(0, 4000);
  return JSON.stringify(v, null, 2).slice(0, 4000);
}

/** A saved thread entry -> transcript row. */
function threadMsg(m: any): Msg {
  if (m.role === 'tool' && m.tool) {
    const ok = m.ok !== false;
    return {
      role: 'tool', text: m.tool, tool: m.tool, id: m.id, args: m.args, ok, status: ok ? 'ok' : 'error', ms: m.durationMs,
      output: ok ? formatToolOutput(m.output) : formatToolOutput(m.error), diff: ok ? m.output?.diff : undefined,
    };
  }
  return { role: m.role, text: m.content, turn: m.turn, images: m.images || undefined };
}

const NAV_TITLES: Record<Nav, string> = {
  thread: '', files: 'Files', images: 'Images', mcp: 'MCP servers', automations: 'Automations', skills: 'Skills', settings: 'Settings',
};

export default function App() {
  const [nav, setNav] = useState<Nav>('thread');
  const [threads, setThreads] = useState<any[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [title, setTitle] = useState('');
  const [messages, setMessages] = useState<Msg[]>([]);
  const [files, setFiles] = useState<string[]>([]);
  const [pending, setPending] = useState<{ tool: string; args: any; rule?: string; mcp?: { server: string; tool: string } } | null>(null);
  const [todos, setTodos] = useState<Todo[]>([]);
  const [plan, setPlan] = useState<string | null>(null);
  const [hooksUntrusted, setHooksUntrusted] = useState(false);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState('');
  const [seed, setSeed] = useState<{ text: string; n: number } | null>(null);
  const [model, setModel] = useState('local:');
  const [permMode, setPermMode] = useState(loadSettings().permissionMode);
  const [effort, setEffortState] = useState(() => localStorage.getItem('mtrini.effort') || loadSettings().defaultEffort);
  const setEffort = (e: string) => {
    setEffortState(e);
    localStorage.setItem('mtrini.effort', e);
  };
  const [branch, setBranch] = useState('—');
  const [project, setProject] = useState('');
  const [ws, setWs] = useState<string | null>(getWorkspace());
  const [threadWs, setThreadWs] = useState<string | null>(null);
  const [folderMode, setFolderMode] = useState<'global' | 'thread'>('global');
  const [cmdOpen, setCmdOpen] = useState(false);
  const [picking, setPicking] = useState(false);
  const [diffOpen, setDiffOpen] = useState(() => loadSettings().showChanges);
  const [diffTick, setDiffTick] = useState(0);
  const [commiting, setCommiting] = useState(false);
  const [commitMsg, setCommitMsg] = useState('');
  const [renaming, setRenaming] = useState<{ id: string; title: string } | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [needsSetup, setNeedsSetup] = useState(false);
  const [openSignal, setOpenSignal] = useState<{ path: string; n: number } | null>(null);
  const abort = useRef<AbortController | null>(null);

  const loadThreads = useCallback(async () => {
    try { setThreads((await api.threads()).threads || []); } catch { /* ignore */ }
  }, []);

  const loadContext = useCallback(async () => {
    loadThreads();
    try {
      const p = await api.project();
      const root = String(p.root || '');
      setProject(root.split(/[/\\]/).filter(Boolean).pop() || '');
    } catch { setProject(''); }
    try { setBranch(await api.branch()); } catch { setBranch('—'); }
    try {
      const provs = (await api.providers()).providers || [];
      setNeedsSetup(!provs.some((p: any) => p.configured));
    } catch { setNeedsSetup(false); }
    try {
      const h = await api.hooks();
      setHooksUntrusted(!!h.present && !h.trusted);
    } catch { setHooksUntrusted(false); }
  }, [loadThreads]);

  useEffect(() => {
    applySettings(loadSettings());
    loadContext();
    const h = (e: Event) => {
      const path = (e as CustomEvent).detail as string;
      setNav('files');
      setOpenSignal((s) => ({ path, n: (s?.n || 0) + 1 }));
    };
    const hp = () => loadContext();
    const hu = () => setPermMode(loadSettings().permissionMode);
    window.addEventListener('mtrini:open', h);
    window.addEventListener('mtrini:providers-changed', hp);
    window.addEventListener('mtrini:ui-changed', hu);
    return () => { window.removeEventListener('mtrini:open', h); window.removeEventListener('mtrini:providers-changed', hp); window.removeEventListener('mtrini:ui-changed', hu); };
  }, [loadContext]);

  useEffect(() => {
    const keys = (e: KeyboardEvent) => {
      const mod = e.ctrlKey || e.metaKey;
      if (mod && e.key.toLowerCase() === 'k') { e.preventDefault(); setCmdOpen((v) => !v); }
      if (mod && e.key === ',') { e.preventDefault(); setNav('settings'); }
      if (mod && e.key.toLowerCase() === 'l') { e.preventDefault(); newThread(); }
    };
    window.addEventListener('keydown', keys);
    return () => window.removeEventListener('keydown', keys);
  }, []); // eslint-disable-line

  useEffect(() => {
    if (!ws) setPicking(true);
  }, []); // eslint-disable-line

  const pickWorkspace = (path: string) => {
    if (folderMode === 'thread' && activeId) {
      api.renameThread(activeId, '', path).then(() => {
        setThreadWs(path);
        setExecOverride(path);
        loadThreads();
        loadContext();
      }).catch((e: any) => setToast(`Folder change failed: ${e.message}`));
      setPicking(false);
      return;
    }
    setWorkspace(path);
    touchRecent(path);
    setWs(path);
    setPicking(false);
    setActiveId(null); setTitle(''); setMessages([]); setFiles([]); setPending(null); setNav('thread');
    setTodos([]); setPlan(null);
    setThreadWs(null);
    setExecOverride(null);
    loadContext();
  };

  const openThread = async (id: string) => {
    try {
      const t = await api.getThread(id);
      setActiveId(id);
      setTitle(t.title || '');
      const tws = t.workspace || null;
      setThreadWs(tws);
      setExecOverride(tws);
      setMessages((t.messages || []).map(threadMsg));
      setFiles([]);
      setPending(null); setPlan(null); setTodos([]);
      setNav('thread');
      loadContext();
      try {
        const sess = await api.agentSession(id);
        setTodos(sess.todos || []);
        if (sess.pending?.kind === 'tool') setPending({ tool: sess.pending.tool, args: sess.pending.args, rule: sess.pending.rule });
        if (sess.pending?.kind === 'plan') setPlan(sess.pending.plan || '');
      } catch { /* no session yet */ }
    } catch { setToast('Thread not found'); }
  };

  const newThread = () => {
    setEffort(loadSettings().defaultEffort);
    setActiveId(null); setTitle(''); setMessages([]); setFiles([]); setPending(null); setNav('thread');
    setTodos([]); setPlan(null);
    setThreadWs(null);
    setExecOverride(null);
  };

  const deleteThread = async (id: string) => {
    try { await api.deleteThread(id); } catch { /* gone */ }
    if (activeId === id) newThread();
    loadThreads();
  };

  const splitModel = () => {
    const [provider, ...rest] = model.split(':');
    return { provider, mid: rest.join(':') || '' };
  };

  /** Stream one /api/agent request (a new message or an answer to an approval) into the transcript. */
  const stream = async (id: string, body: any) => {
    setBusy(true);
    abort.current = new AbortController();
    let acc = '';
    const push = (e: Msg) => setMessages((m) => [...m.slice(-300), e]);
    const fmt = (v: any) => formatToolOutput(v);
    const update = (match: (x: Msg) => boolean, patch: Partial<Msg>, fallback?: Msg) => setMessages((m) => {
      for (let k = m.length - 1; k >= 0; k--) {
        if (match(m[k])) { const next = m.slice(); next[k] = { ...m[k], ...patch }; return next; }
      }
      return fallback ? [...m, fallback] : m;
    });
    setStatus('Starting…');
    try {
      for await (const ev of sse('/api/agent', { ...body, threadId: id }, abort.current.signal)) {
        if (ev.type === 'status') {
          setStatus(ev.message || '');
        } else if (ev.type === 'turn') {
          update((x) => x.role === 'user' && !x.turn, { turn: ev.turn });
        } else if (ev.type === 'assistant_delta') {
          acc += ev.delta;
          setMessages((m) => {
            const last = m[m.length - 1];
            if (last && last.role === 'assistant' && !last.kind) return [...m.slice(0, -1), { role: 'assistant', text: acc }];
            return [...m, { role: 'assistant', text: acc }];
          });
        } else if (ev.type === 'tool_start') {
          // The streamed text is already on screen: seal it so the next delta starts a new message.
          if (acc) {
            setMessages((m) => {
              const last = m[m.length - 1];
              return last && last.role === 'assistant' && !last.kind ? [...m.slice(0, -1), { ...last, kind: 'done' }] : m;
            });
            acc = '';
          }
          push({ role: 'tool', text: ev.tool, tool: ev.tool, args: ev.args, id: ev.id, parent: ev.parent, status: 'running' });
          const p = ev.args?.path || ev.args?.dst;
          if (p && ['write_file', 'edit_file', 'move_file'].includes(ev.tool)) {
            setFiles((f) => (f.includes(p) ? f : [...f, p]));
          }
        } else if (ev.type === 'tool_result') {
          const done: Partial<Msg> = {
            status: ev.ok ? 'ok' : 'error', ok: ev.ok, ms: ev.durationMs,
            output: ev.ok ? fmt(ev.output) : fmt(ev.error), diff: ev.ok ? ev.output?.diff : undefined,
          };
          update((x) => x.role === 'tool' && x.status === 'running' && (ev.id ? x.id === ev.id : x.tool === ev.tool), done,
            { role: 'tool', text: ev.tool, tool: ev.tool, args: ev.args, id: ev.id, parent: ev.parent, ...done } as Msg);
          if (['write_file', 'edit_file', 'move_file', 'delete_file'].includes(ev.tool)) setDiffTick((t) => t + 1);
        } else if (ev.type === 'subagent') {
          if (ev.status === 'start') push({ role: 'tool', text: 'task', tool: 'task', id: ev.id, args: { description: ev.description }, status: 'running' });
          else update((x) => x.id === ev.id && x.tool === 'task', { status: 'ok', ok: true, output: String(ev.result || '') });
        } else if (ev.type === 'todos') {
          setTodos(ev.todos || []);
        } else if (ev.type === 'plan') {
          setPlan(ev.plan || '');
        } else if (ev.type === 'mode') {
          setPermMode(ev.mode);
          saveSettings({ permissionMode: ev.mode });
        } else if (ev.type === 'compacted') {
          push({ role: 'note', text: `Earlier conversation summarized to save context (~${ev.before} → ~${ev.after} tokens).` });
        } else if (ev.type === 'hooks_untrusted') {
          setHooksUntrusted(true);
        } else if (ev.type === 'permission_request') {
          setPending({ tool: ev.tool, args: ev.args, rule: ev.rule, mcp: ev.mcp });
        } else if (ev.type === 'error') {
          push({ role: 'assistant', text: `Error: ${ev.message}` });
        } else if (ev.type === 'done') {
          if (ev.pendingApproval) setPending(ev.pendingApproval);
          loadThreads();
        }
      }
    } catch (e: any) {
      if (String(e?.name) === 'AbortError') push({ role: 'assistant', text: '_Stopped._' });
      else push({ role: 'assistant', text: `Error: ${e.message || e}` });
    } finally { setBusy(false); setStatus(''); abort.current = null; }
  };

  const send = async (text: string, images?: Img[]) => {
    const { provider, mid } = splitModel();
    if (!mid) { setToast('Pick a model id first (or configure a provider in Settings)'); return; }
    let tid = activeId;
    if (!tid) {
      const th = await api.createThread(text.slice(0, 42) || 'Untitled');
      tid = th.id;
      setActiveId(tid);
      setTitle(th.title);
      if (th.workspace) { setThreadWs(th.workspace); setExecOverride(th.workspace); }
      loadThreads();
    }
    setPending(null); setPlan(null);
    setMessages((m) => [...m, { role: 'user', text, images: images?.length || undefined }]);
    // Threads from before 0.8 have no agent session yet: send the visible transcript once.
    const history = messages.filter((m) => m.role === 'user' || m.role === 'assistant').map((m) => ({ role: m.role, content: m.text }));
    await stream(tid as string, {
      provider, model: mid, message: text, history, permissionMode: permMode, effort,
      useSkills: loadSettings().useSkills, useInstructions: loadSettings().useInstructions,
      images: (images || []).map(({ mime, data }) => ({ mime, data })),
    });
  };

  /** Answer the paused turn and let the same agent loop carry on. */
  const resume = (answer: Record<string, any>) => {
    if (!activeId) return;
    const { provider, mid } = splitModel();
    return stream(activeId, { provider, model: mid, message: '', permissionMode: permMode, effort, resume: answer });
  };

  const approve = async (always = false) => {
    if (!pending) return;
    setPending(null);
    await resume({ decision: always ? 'always' : 'allow' });
  };

  const deny = async () => {
    if (!pending) return;
    setPending(null);
    await resume({ decision: 'deny' });
  };

  const decidePlan = async (d: PlanDecision) => {
    if (plan) setMessages((m) => [...m, { role: 'plan', text: plan }]);
    setPlan(null);
    await resume(d);
  };

  const rewind = async (turn: number) => {
    if (!activeId || busy) return;
    if (loadSettings().confirmDelete && !window.confirm('Rewind to before this message?\n\nFiles the agent changed from here on are put back (changes made by shell commands are not), and the conversation from here on is removed.')) return;
    try {
      const r = await api.rewind(activeId, turn);
      setTodos([]);
      await openThread(activeId);
      if (r.prompt) setSeed((x) => ({ text: r.prompt, n: (x?.n || 0) + 1 }));
      const f = r.files || { restored: [], removed: [], skipped: [] };
      setToast(`Rewound. Files restored: ${f.restored.length}, removed: ${f.removed.length}${f.skipped.length ? `, not restorable: ${f.skipped.length}` : ''}`);
      setDiffTick((t) => t + 1);
    } catch (e: any) { setToast(`Rewind failed: ${e.message}`); }
  };

  const trustHooks = async () => {
    try { await api.trustHooks(); setHooksUntrusted(false); setToast('Hooks trusted for this project'); } catch (e: any) { setToast(`Could not trust hooks: ${e.message}`); }
  };

  const runCommand = async (name: string) => {
    const note = (text: string) => setMessages((m) => [...m, { role: 'note', text }]);
    if (name === 'clear') { newThread(); return; }
    if (name === 'compact') {
      if (!activeId) { note('Nothing to compact yet.'); return; }
      const { provider, mid } = splitModel();
      setBusy(true); setStatus('Summarizing earlier conversation…');
      try {
        const r = await api.compact(activeId, provider, mid);
        note(r.compacted ? `Summarized ${r.summarized} earlier messages (~${r.before} → ~${r.after} tokens). The latest turn is kept word for word.` : `Nothing compacted: ${r.reason || 'the conversation is still short'}.`);
      } catch (e: any) { note(`Compaction failed: ${e.message}`); } finally { setBusy(false); setStatus(''); }
      return;
    }
    if (name === 'init') {
      send('Look through this project and write .mtrini/instructions.md: a short guide for an AI coding agent working here (what the project is, how to build, test and run it, code style, the folders that matter, things to avoid). Keep it under 60 lines. If the file already exists, improve it instead.');
      return;
    }
    if (name === 'agents') {
      try {
        const agents = (await api.project()).agents || [];
        note(agents.length
          ? `### Subagents\n${agents.map((a: any) => `- \`${a.name}\` ${String(a.content || '').split('\n').find((l: string) => l.trim() && !l.startsWith('---')) || ''}`).join('\n')}\n\nThe agent can start one with its task tool, e.g. "use the ${agents[0].name} agent to …".`
          : 'No subagents yet. Add Markdown files to `.mtrini/agents/` (for example `reviewer.md` with instructions); the agent can then start them with its task tool.');
      } catch { note('Could not read the project.'); }
      return;
    }
    if (name === 'permissions') {
      try {
        const { allow } = await api.permissions();
        note(allow.length
          ? `### Always allowed\n${allow.map((r) => `- \`${r}\``).join('\n')}\n\nEdit or remove these in Settings → Agent.`
          : 'Nothing is always allowed yet. Use **Always allow** on an approval card to add a rule.');
      } catch { note('Could not read permission rules.'); }
      return;
    }
    if (name === 'skills') { setNav('skills'); return; }
    if (name === 'mcp') { setNav('mcp'); return; }
    if (name === 'settings') { setNav('settings'); return; }
    if (name === 'help') {
      let skillLines = '';
      try {
        const sk = (await api.skills()).skills || [];
        skillLines = sk.length ? sk.map((x) => `- \`/${x.name}\` ${x.description}`).join('\n') : '- No skills yet. Open \`/skills\` to add one.';
      } catch { skillLines = '- Skills are unavailable (backend not reachable).'; }
      const cmdLines = BUILTIN_COMMANDS.map((c) => `- \`/${c.name}\` ${c.description}`).join('\n');
      setMessages((m) => [...m, { role: 'note', text: `### Commands\n${cmdLines}\n### Skills\n${skillLines}\n\nShortcuts: Ctrl+K command menu, Ctrl+L new session, Ctrl+, settings.` }]);
    }
  };

  const useInSession = (text: string) => {
    setNav('thread');
    setSeed((s) => ({ text, n: (s?.n || 0) + 1 }));
  };

  const doCommit = async () => {
    if (!commitMsg.trim()) return;
    try {
      await api.gitCommit(commitMsg.trim());
      setCommitMsg(''); setCommiting(false); setDiffTick((t) => t + 1);
      setToast('Committed');
    } catch (e: any) { setToast(`Commit failed: ${e.message}`); }
  };

  const doRename = async () => {
    if (!renaming || !renaming.title.trim()) return;
    try {
      await api.renameThread(renaming.id, renaming.title.trim());
      setTitle(renaming.title.trim());
      setRenaming(null);
      loadThreads();
    } catch (e: any) { setToast(`Rename failed: ${e.message}`); }
  };

  return (
    <div className="shell">
      <div className="win" role="application" aria-label="Mtrini Workspace">
        <Sidebar nav={nav} go={setNav} threads={threads} activeThread={activeId}
          onThread={openThread} onNew={newThread} onDelete={deleteThread}
          onRename={(id, t) => setRenaming({ id, title: t })}
          workspace={ws} onPickWorkspace={() => { setFolderMode('global'); setPicking(true); }} />
        <div className="main">
          <TopBar title={nav === 'thread' ? title : NAV_TITLES[nav]} project={project}
            onOpen={() => api.openFolder().catch(() => setToast('Could not open folder'))}
            onCommit={() => setCommiting(true)}
            diffOpen={diffOpen} onToggleDiff={() => setDiffOpen((v) => !v)} />
          <div className="body">
            {nav === 'thread' && (
              <ThreadView messages={messages} busy={busy} status={status} pending={pending} files={files}
                branch={branch} model={model} setModel={setModel}
                onSend={(t, imgs) => send(t, imgs)} onCommand={runCommand} onStop={() => abort.current?.abort()}
                project={project} seed={seed}
                onApprove={approve} onDeny={deny}
                todos={todos} plan={plan} onPlan={decidePlan}
                hooksUntrusted={hooksUntrusted} onTrustHooks={trustHooks} onRewind={rewind}
                needsSetup={needsSetup} onGoSettings={() => setNav('settings')}
                threadWs={threadWs} onPickThreadFolder={() => { setFolderMode('thread'); setPicking(true); }}
                effort={effort} setEffort={setEffort} />
            )}
            {nav === 'files' && <FilesView openSignal={openSignal} />}
            {nav === 'images' && <ImagesView />}
            {nav === 'mcp' && <MCPView />}
            {nav === 'skills' && <SkillsView onUse={useInSession} />}
            {nav === 'automations' && <AutomationsView onRun={async (tid, prompt) => {
              await openThread(tid);
              send(prompt);
            }} />}
            {nav === 'settings' && <div className="view"><SettingsPanel onToast={setToast} /></div>}
            {diffOpen && (nav === 'thread' || nav === 'files') && <DiffPanel tick={diffTick} />}
          </div>
        </div>
      </div>
      {picking && (
        <WorkspacePicker
          current={folderMode === 'thread' ? threadWs : ws}
          onClose={() => { if (ws) setPicking(false); }}
          onPick={pickWorkspace} />
      )}
      {cmdOpen && (
        <CommandMenu
          onClose={() => setCmdOpen(false)}
          threads={threads}
          onThread={openThread}
          onAction={(a: ActionId) => {
            if (a === 'new-thread') newThread();
            else if (a === 'go-files') setNav('files');
            else if (a === 'go-images') setNav('images');
            else if (a === 'go-mcp') setNav('mcp');
            else if (a === 'go-skills') setNav('skills');
            else if (a === 'go-automations') setNav('automations');
            else if (a === 'go-settings') setNav('settings');
            else if (a === 'toggle-diff') setDiffOpen((v) => !v);
            else if (a === 'open-folder') api.openFolder().catch(() => setToast('Could not open folder'));
            else if (a === 'commit') setCommiting(true);
            else if (a === 'pick-workspace') { setFolderMode('global'); setPicking(true); }
          }} />
      )}
      {commiting && (
        <div className="modal" onClick={() => setCommiting(false)} role="dialog" aria-label="Commit changes">
          <div className="sheet" onClick={(e) => e.stopPropagation()}>
            <strong>Commit changes</strong>
            <label className="f">Message</label>
            <textarea className="t" rows={3} value={commitMsg} onChange={(e) => setCommitMsg(e.target.value)} placeholder="Describe the change" />
            <div className="row" style={{ marginTop: 10 }}>
              <button className="btn primary" onClick={doCommit}>Commit</button>
              <button className="btn" onClick={() => setCommiting(false)}>Cancel</button>
            </div>
          </div>
        </div>
      )}
      {renaming && (
        <div className="modal" onClick={() => setRenaming(null)} role="dialog" aria-label="Rename thread">
          <div className="sheet" onClick={(e) => e.stopPropagation()}>
            <strong>Rename thread</strong>
            <label className="f">Title</label>
            <input className="t" value={renaming.title} onChange={(e) => setRenaming({ ...renaming, title: e.target.value })} />
            <div className="row" style={{ marginTop: 10 }}>
              <button className="btn primary" onClick={doRename}>Rename</button>
              <button className="btn" onClick={() => setRenaming(null)}>Cancel</button>
            </div>
          </div>
        </div>
      )}
      {toast && <div role="status" style={{ position: 'fixed', bottom: 20, right: 16, background: 'var(--bg3)', border: '1px solid var(--border)', borderRadius: 8, padding: '6px 12px' }} onClick={() => setToast(null)}>{toast}</div>}
    </div>
  );
}
