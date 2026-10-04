import React, { useCallback, useEffect, useRef, useState } from 'react';
import { api, getWorkspace, setExecOverride, setWorkspace, sse, touchRecent } from './api/client';
import CommandMenu, { ActionId } from './components/CommandMenu';
import { applySettings, loadSettings } from './lib/settings';
import DiffPanel from './components/DiffPanel';
import FilesView from './components/FilesView';
import ImagesView from './components/ImagesView';
import MCPView from './components/MCPView';
import { AutomationsView, SkillsView } from './components/Panels';
import SettingsPanel from './components/SettingsPanel';
import Sidebar, { Nav } from './components/Sidebar';
import ThreadView, { Msg } from './components/ThreadView';
import TopBar from './components/TopBar';
import WorkspacePicker from './components/WorkspacePicker';

export default function App() {
  const [nav, setNav] = useState<Nav>('thread');
  const [threads, setThreads] = useState<any[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [title, setTitle] = useState('');
  const [messages, setMessages] = useState<Msg[]>([]);
  const [files, setFiles] = useState<string[]>([]);
  const [pending, setPending] = useState<{ tool: string; args: any; mcp?: { server: string; tool: string } } | null>(null);
  const [busy, setBusy] = useState(false);
  const [model, setModel] = useState('local:');
  const [permMode, setPermMode] = useState(loadSettings().permissionMode);
  const [effort, setEffortState] = useState(() => localStorage.getItem('mtrini.effort') || 'off');
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
  const [diffOpen, setDiffOpen] = useState(true);
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
      setMessages((t.messages || []).map((m: any) => ({ role: m.role, text: m.content })));
      setFiles([]);
      setPending(null);
      setNav('thread');
      loadContext();
    } catch { setToast('Thread not found'); }
  };

  const newThread = () => {
    setActiveId(null); setTitle(''); setMessages([]); setFiles([]); setPending(null); setNav('thread');
    setThreadWs(null);
    setExecOverride(null);
  };

  const deleteThread = async (id: string) => {
    try { await api.deleteThread(id); } catch { /* gone */ }
    if (activeId === id) newThread();
    loadThreads();
  };

  const send = async (text: string, seeded = false) => {
    const [provider, ...rest] = model.split(':');
    const mid = rest.join(':') || '';
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
    const id = tid as string;
    if (!seeded) await api.appendMsg(id, 'user', text).catch(() => {});
    setMessages((m) => [...m, { role: 'user', text }]);
    setBusy(true);
    abort.current = new AbortController();
    let acc = '';
    const push = (e: Msg) => setMessages((m) => [...m.slice(-200), e]);
    const history = [...messages.filter((m) => m.role !== 'tool').map((m) => ({ role: m.role, content: m.text })),
      { role: 'user', content: text }];
    try {
      for await (const ev of sse('/api/agent', { provider, model: mid, message: text, history, permissionMode: permMode, effort }, abort.current.signal)) {
        if (ev.type === 'assistant_delta') {
          acc += ev.delta;
          setMessages((m) => {
            const last = m[m.length - 1];
            if (last && last.role === 'assistant' && !last.kind) return [...m.slice(0, -1), { role: 'assistant', text: acc }];
            return [...m, { role: 'assistant', text: acc }];
          });
        } else if (ev.type === 'tool_start') {
          if (acc) { push({ role: 'assistant', text: acc, kind: 'done' }); acc = ''; }
          push({ role: 'tool', text: `${ev.tool} ${JSON.stringify(ev.args).slice(0, 160)}` });
          const p = ev.args?.path || ev.args?.dst;
          if (p && ['write_file', 'edit_file', 'move_file'].includes(ev.tool)) {
            setFiles((f) => (f.includes(p) ? f : [...f, p]));
          }
        } else if (ev.type === 'tool_result') {
          push({ role: 'tool', text: `${ev.tool}`, kind: (ev.output ? JSON.stringify(ev.output).slice(0, 600) : ev.error || ''), ok: ev.ok, ms: ev.durationMs });
          if (['write_file', 'edit_file', 'move_file', 'delete_file'].includes(ev.tool)) setDiffTick((t) => t + 1);
        } else if (ev.type === 'permission_request') {
          setPending({ tool: ev.tool, args: ev.args, mcp: ev.mcp });
        } else if (ev.type === 'error') {
          push({ role: 'assistant', text: `Error: ${ev.message}` });
        } else if (ev.type === 'done') {
          if (ev.pendingApproval) setPending(ev.pendingApproval);
          if (acc) { await api.appendMsg(id, 'assistant', acc).catch(() => {}); }
          loadThreads();
        }
      }
    } catch (e: any) {
      if (String(e?.name) === 'AbortError') {
        if (acc) { await api.appendMsg(id, 'assistant', acc + '\n\n*(stopped)*').catch(() => {}); }
        push({ role: 'assistant', text: '_Stopped._' });
      } else {
        push({ role: 'assistant', text: `Error: ${e.message || e}` });
      }
    } finally { setBusy(false); abort.current = null; }
  };

  const approve = async () => {
    if (!pending) return;
    const p = pending;
    setPending(null);
    const [provider, ...rest] = model.split(':');
    setMessages((m) => [...m, { role: 'tool', text: `✔ approved ${p.tool}` }]);
    try {
      const r = await fetch('/api/agent', {
        method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ provider, model: rest.join(':') || '', message: '', history: [], approve: p }),
      });
      const data = await r.json();
      setMessages((m) => [...m, { role: 'tool', text: p.tool, kind: JSON.stringify(data.output || data.error || '').slice(0, 600), ok: data.ok }]);
      setDiffTick((t) => t + 1);
    } catch (e: any) {
      setMessages((m) => [...m, { role: 'tool', text: p.tool, kind: String(e.message || e), ok: false }]);
    }
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
          <TopBar title={nav === 'thread' ? title : nav} project={project}
            onOpen={() => api.openFolder().catch(() => setToast('Could not open folder'))}
            onCommit={() => setCommiting(true)}
            diffOpen={diffOpen} onToggleDiff={() => setDiffOpen((v) => !v)} />
          <div className="body">
            {nav === 'thread' && (
              <ThreadView messages={messages} busy={busy} pending={pending} files={files}
                branch={branch} model={model} setModel={setModel}
                onSend={(t) => send(t)} onStop={() => abort.current?.abort()}
                onApprove={approve} onDeny={() => setPending(null)}
                needsSetup={needsSetup} onGoSettings={() => setNav('settings')}
                threadWs={threadWs} onPickThreadFolder={() => { setFolderMode('thread'); setPicking(true); }}
                effort={effort} setEffort={setEffort} />
            )}
            {nav === 'files' && <FilesView openSignal={openSignal} />}
            {nav === 'images' && <ImagesView />}
            {nav === 'mcp' && <MCPView />}
            {nav === 'skills' && <SkillsView />}
            {nav === 'automations' && <AutomationsView onRun={async (tid, prompt) => {
              await openThread(tid);
              send(prompt, true);
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
