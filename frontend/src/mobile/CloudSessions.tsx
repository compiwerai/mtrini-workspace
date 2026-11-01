import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Cloud, freeChat, type CloudMsg, type CloudThread, type CloudThreadMeta, type Task } from '../remote/cloud';
import type { PhoneBridge } from '../remote/bridge';

/**
 * Every session from your PCs, saved in Mtrini Cloud: read them anywhere, even with the PC off. Send a session
 * more work and its PC runs it now, or when it's back. Chats started here use the free model, no PC needed.
 */
type Props = { cloud: Cloud; bridge: PhoneBridge; devices: Record<string, string>; onLive: (pcId: string, workspace: string) => void };

const folder = (p: string) => p.split(/[\\/]/).filter(Boolean).pop() || p;
const ago = (ts: number) => {
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return new Date(ts * 1000).toLocaleDateString([], { month: 'short', day: 'numeric' });
};
const STATUS: Record<string, string> = {
  queued: 'Waiting for the PC', running: 'Running on the PC…', waiting: 'Waiting for your OK. Open it live to answer.',
  done: 'Done', failed: 'Failed', cancelled: 'Cancelled',
};

export default function CloudSessions(props: Props) {
  const { cloud } = props;
  const [list, setList] = useState<CloudThreadMeta[]>(() => cloud.cachedThreads());
  const [offline, setOffline] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const [q, setQ] = useState('');

  const refresh = () => cloud.threads().then((l) => { setList(l); setOffline(false); }).catch(() => setOffline(true));
  useEffect(() => {
    refresh();
    const t = window.setInterval(refresh, 15000);
    return () => window.clearInterval(t);
  }, [cloud]);

  const groups = useMemo(() => {
    const out = new Map<string, CloudThreadMeta[]>();
    const needle = q.trim().toLowerCase();
    for (const t of list) {
      if (needle && !`${t.title} ${t.preview} ${t.workspace}`.toLowerCase().includes(needle)) continue;
      const k = t.pc ? `${props.devices[t.pc] || 'PC'} · ${folder(t.workspace)}` : 'Chats on this phone';
      out.set(k, [...(out.get(k) || []), t]);
    }
    return [...out.entries()];
  }, [list, q, props.devices]);

  if (open !== null) {
    return <SessionView {...props} id={open} meta={list.find((t) => t.id === open)} onBack={() => { setOpen(null); refresh(); }} />;
  }

  const newChat = async () => {
    const id = [...crypto.getRandomValues(new Uint8Array(6))].map((b) => b.toString(16).padStart(2, '0')).join('');
    const now = Math.floor(Date.now() / 1000);
    localStorage.setItem(`mtrini.phone.cache.t.${id}`, JSON.stringify({ id, title: 'New chat', created: now, updated: now, messages: [] }));
    setOpen(id);
  };

  return (
    <div className="phone-screen phone-list">
      <div className="row phone-head">
        <h1>Sessions</h1>
        <button className="btn primary" onClick={newChat}>New chat</button>
      </div>
      <input className="t" placeholder="Search sessions" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search sessions" />
      {offline && <p className="notice">No connection. Showing the sessions saved on this phone.</p>}
      {list.length === 0 && !offline && (
        <p className="hint">Nothing saved yet. On your PC: Settings → Account → turn on Cloud sync. Your sessions show up here,
          and stay here when the PC is off.</p>
      )}
      {groups.map(([name, items]) => (
        <section key={name} className="phone-group">
          <div className="label-caps">{name}</div>
          {items.map((t) => (
            <button key={t.id} className="btn wide listbtn" onClick={() => setOpen(t.id)}>
              <span className="row" style={{ justifyContent: 'space-between', gap: 8 }}>
                <strong>{t.title}</strong>
                <span className="hint">{ago(t.updated)}</span>
              </span>
              <span className="hint">{t.preview || `${t.messages} messages`}</span>
            </button>
          ))}
        </section>
      ))}
    </div>
  );
}

function Message({ m }: { m: CloudMsg }) {
  const [openTool, setOpenTool] = useState(false);
  if (m.role === 'tool') {
    const detail = typeof m.output === 'string' ? m.output : m.output ? JSON.stringify(m.output, null, 1) : m.error || '';
    return (
      <div className={`ctool${m.ok === false ? ' bad' : ''}`}>
        <button className="ctool-head mono" onClick={() => setOpenTool((v) => !v)}>
          {m.tool}{m.args?.path ? ` ${m.args.path}` : m.args?.command ? ` ${String(m.args.command).slice(0, 60)}` : ''}
        </button>
        {openTool && detail && <pre>{String(detail).slice(0, 4000)}</pre>}
      </div>
    );
  }
  if (m.role !== 'user' && m.role !== 'assistant') return null;
  return <div className={`cmsg ${m.role}`}>{m.content}{m.imagesOmitted ? <span className="hint"> ({m.imagesOmitted} image{m.imagesOmitted > 1 ? 's' : ''} on the PC)</span> : null}</div>;
}

function SessionView({ cloud, bridge, devices, onLive, id, meta, onBack }: Props & { id: string; meta?: CloudThreadMeta; onBack: () => void }) {
  const [t, setT] = useState<(CloudThread & { rev?: number }) | null>(() => cloud.cachedThread(id));
  const [tasks, setTasks] = useState<Task[]>([]);
  const [text, setText] = useState('');
  const [mode, setMode] = useState<'ask' | 'auto'>('ask');
  const [busy, setBusy] = useState(false);
  const [answer, setAnswer] = useState('');
  const [err, setErr] = useState('');
  const end = useRef<HTMLDivElement>(null);
  const pc = meta?.pc || '';
  const workspace = meta?.workspace || t?.workspace || '';
  const online = pc ? bridge.pcs.some((p) => p.id === pc) : false;
  const paired = pc ? bridge.isPaired(pc) : false;

  useEffect(() => {
    if (!meta) return; // a new chat: nothing in the cloud yet
    let live = true;
    const load = () => {
      cloud.thread(id).then((x) => live && setT(x)).catch(() => {});
      if (pc) cloud.tasks().then((all) => live && setTasks(all.filter((k) => k.thread_id === id))).catch(() => {});
    };
    load();
    const timer = window.setInterval(load, 5000);
    return () => { live = false; window.clearInterval(timer); };
  }, [cloud, id, pc, !!meta]);
  useEffect(() => { end.current?.scrollIntoView({ block: 'end' }); }, [t?.messages.length, answer, tasks.length]);

  const send = async () => {
    const prompt = text.trim();
    if (!prompt || busy) return;
    setBusy(true); setErr('');
    try {
      if (pc) {
        const k = await cloud.queue(bridge, pc, id, workspace, prompt, mode);
        setTasks((all) => [...all, k]);
        setText('');
      } else {
        const now = Math.floor(Date.now() / 1000);
        const base = t || { id, title: 'New chat', created: now, updated: now, messages: [] };
        const asked: CloudThread = { ...base, title: base.messages.length ? base.title : prompt.slice(0, 60),
          updated: now, messages: [...base.messages, { role: 'user', content: prompt, ts: now }] };
        setT(asked); setText('');
        const history = asked.messages.filter((m) => m.role === 'user' || m.role === 'assistant').slice(-30)
          .map((m) => ({ role: m.role, content: String(m.content || '') }));
        const reply = await freeChat([{ role: 'system', content: 'You are Mtrini, a helpful assistant in the Mtrini Workspace phone app. Be concise.' }, ...history], setAnswer);
        const done = { ...asked, updated: Math.floor(Date.now() / 1000), messages: [...asked.messages, { role: 'assistant', content: reply, ts: Math.floor(Date.now() / 1000) }] };
        setAnswer('');
        setT(done);
        const rev = await cloud.save(done);
        setT({ ...done, rev });
      }
    } catch (e: any) {
      setErr(String(e.message || e)); setAnswer('');
    } finally { setBusy(false); }
  };

  const open = tasks.filter((k) => k.status !== 'done' && k.status !== 'cancelled');
  return (
    <div className="phone-session">
      <header className="phone-bar">
        <button className="btn" onClick={onBack}>Back</button>
        <span className="phone-title">{t?.title || meta?.title || 'Chat'}
          <span className="hint">{pc ? ` ${devices[pc] || 'PC'} · ${folder(workspace)}` : ' Free model'}</span></span>
        {pc && online && paired && <button className="btn" onClick={() => onLive(pc, workspace)}>Open live</button>}
      </header>
      <div className="cthread">
        {!t && <p className="hint">Loading…</p>}
        {t?.messages.length === 0 && !pc && <p className="hint">Chat with the free model here, no PC needed. To work on code, open a session from your PC.</p>}
        {t?.messages.map((m, i) => <Message key={i} m={m} />)}
        {answer && <div className="cmsg assistant">{answer}</div>}
        {open.map((k) => (
          <div key={k.id} className="cmsg user pending">
            {k.local || 'Sent from another phone'}
            <span className="hint">{STATUS[k.status] || k.status}{k.error ? `: ${k.error}` : ''}</span>
            {k.status === 'queued' && <button className="btn" onClick={() => cloud.cancel(k.id).then(() => setTasks((a) => a.filter((x) => x.id !== k.id))).catch(() => {})}>Cancel</button>}
          </div>
        ))}
        <div ref={end} />
      </div>
      <footer className="ccompose">
        {pc && !paired && <p className="notice">Pair with {devices[pc] || 'this PC'} first (PCs tab) to send it work.</p>}
        {pc && paired && <p className="hint">{online ? 'Your PC is online: it starts right away.' : 'Your PC is offline: it runs this when it’s back.'}</p>}
        {err && <p className="notice" role="alert">{err}</p>}
        <div className="row" style={{ gap: 8, alignItems: 'flex-end' }}>
          <textarea className="t" rows={2} value={text} placeholder={pc ? 'What should your PC do next?' : 'Message the free model'}
            onChange={(e) => setText(e.target.value)} disabled={busy || (!!pc && !paired)} />
          <button className="btn primary" onClick={send} disabled={busy || !text.trim() || (!!pc && !paired)}>{pc ? 'Send to PC' : 'Send'}</button>
        </div>
        {pc && paired && (
          <label className="hint" style={{ display: 'flex', gap: 6, alignItems: 'center', marginTop: 6 }}>
            <input type="checkbox" checked={mode === 'auto'} onChange={(e) => setMode(e.target.checked ? 'auto' : 'ask')} />
            Auto mode (only if you allowed it for this phone on the PC)
          </label>
        )}
      </footer>
    </div>
  );
}
