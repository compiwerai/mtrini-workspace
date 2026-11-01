import React, { useCallback, useEffect, useRef, useState } from 'react';
import { I } from './Icon';

/**
 * Mtrini Mail: mail between Mtrini accounts (cloud/src/mail.js). The PC reaches it through its backend
 * (/api/mail), the phone straight from Mtrini Cloud; `call` hides which.
 */
export type MailCall = (path: string, init?: RequestInit) => Promise<Response>;
type Box = 'inbox' | 'starred' | 'sent' | 'archive' | 'trash';
type Msg = { id: string; box: string; conv: string; from: string; to: string[]; subject: string; snippet?: string; body?: string;
  unread: boolean; starred: boolean; created: number };

const BOXES: { id: Box; label: string }[] = [
  { id: 'inbox', label: 'Inbox' }, { id: 'starred', label: 'Starred' }, { id: 'sent', label: 'Sent' },
  { id: 'archive', label: 'Archive' }, { id: 'trash', label: 'Trash' },
];

function when(ts: number) {
  const d = new Date(ts * 1000);
  const today = new Date();
  return d.toDateString() === today.toDateString()
    ? d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    : d.toLocaleDateString([], { month: 'short', day: 'numeric' });
}

export default function MailView({ call, onToast }: { call: MailCall; onToast?: (s: string) => void }) {
  const [me, setMe] = useState<{ name: string | null; unread: number } | null>(null);
  const [problem, setProblem] = useState('');
  const [box, setBox] = useState<Box>('inbox');
  const [q, setQ] = useState('');
  const [list, setList] = useState<Msg[] | null>(null);
  const [open, setOpen] = useState<{ message: Msg; conversation: Msg[] } | null>(null);
  const [draft, setDraft] = useState<{ to: string; subject: string; body: string; reply_to?: string } | null>(null);
  const toast = onToast || (() => {});

  const ask = useCallback(async (path: string, init?: RequestInit) => {
    const r = await call(path, init);
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw Object.assign(new Error(data?.error?.message || data?.detail || `Mtrini Cloud answered ${r.status}.`), { status: r.status, data });
    return data;
  }, [call]);

  const loadMe = useCallback(() => ask('/mail/me').then((m) => { setMe(m); setProblem(''); })
    .catch((e) => setProblem(e.status === 401 ? 'Sign in to use Mtrini Mail.' : e.message)), [ask]);
  const loadList = useCallback(() => {
    if (!me?.name) return;
    ask(`/mail?box=${box}${q ? `&q=${encodeURIComponent(q)}` : ''}`).then((d) => setList(d.messages)).catch((e) => toast(e.message));
  }, [ask, box, q, me?.name]);

  useEffect(() => { loadMe(); }, [loadMe]);
  useEffect(() => { setList(null); loadList(); }, [loadList]);
  useEffect(() => {
    const t = window.setInterval(() => { loadMe(); loadList(); }, 20000);
    return () => window.clearInterval(t);
  }, [loadMe, loadList]);

  const read = async (m: Msg) => {
    try {
      setOpen(await ask(`/mail/${m.id}`));
      if (m.unread) { setList((l) => l && l.map((x) => (x.id === m.id ? { ...x, unread: false } : x))); loadMe(); }
    } catch (e: any) { toast(e.message); }
  };
  const change = async (m: Msg, patch: Partial<Pick<Msg, 'unread' | 'starred' | 'box'>>, msg?: string) => {
    try {
      await ask(`/mail/${m.id}`, { method: 'POST', body: JSON.stringify(patch) });
      if (patch.box || patch.unread) setOpen(null);
      if (msg) toast(msg);
      loadList(); loadMe();
    } catch (e: any) { toast(e.message); }
  };
  const remove = async (m: Msg) => {
    try {
      const r = await ask(`/mail/${m.id}`, { method: 'DELETE' });
      toast(r.deleted ? 'Deleted for good' : 'Moved to Trash');
      setOpen(null); loadList();
    } catch (e: any) { toast(e.message); }
  };

  if (problem) return <div className="mail"><div className="empty">{problem}</div></div>;
  if (!me) return <div className="mail"><div className="empty">Loading…</div></div>;
  if (!me.name) return <ClaimName ask={ask} onDone={(name) => setMe({ name, unread: 0 })} />;

  const reply = (m: Msg, all = false) => {
    const others = all ? [m.from, ...m.to] : [m.from === me.name ? m.to[0] : m.from];
    setDraft({ to: [...new Set(others.filter((n) => n && n !== me.name))].join(', ') || m.from,
      subject: /^re:/i.test(m.subject) ? m.subject : `Re: ${m.subject}`, body: '', reply_to: m.id });
  };

  return (
    <div className={`mail${open || draft ? ' reading' : ''}`}>
      <aside className="mail-boxes">
        <button className="btn primary wide" onClick={() => setDraft({ to: '', subject: '', body: '' })}>{I.pencil()} Write</button>
        <nav className="nav">
          {BOXES.map((b) => (
            <button key={b.id} className={box === b.id ? 'on' : ''} onClick={() => { setBox(b.id); setOpen(null); setDraft(null); }}>
              {b.label}{b.id === 'inbox' && me.unread > 0 && <span className="count">{me.unread}</span>}
            </button>
          ))}
        </nav>
        <p className="hint mail-me">You are <strong>{me.name}@mtrini</strong>. Mail goes between Mtrini accounts only.</p>
      </aside>
      <section className="mail-list">
        <div className="mail-search">
          {I.search()}
          <input className="t" placeholder={`Search ${BOXES.find((b) => b.id === box)!.label.toLowerCase()}`} value={q}
            onChange={(e) => setQ(e.target.value)} aria-label="Search mail" />
        </div>
        {list === null && <div className="empty">Loading…</div>}
        {list?.length === 0 && <div className="empty">{q ? 'Nothing matches.' : box === 'inbox' ? 'No mail yet. Tell a friend your name.' : 'Nothing here.'}</div>}
        {list?.map((m) => (
          <div key={m.id} role="button" tabIndex={0} className={`mail-row${m.unread ? ' unread' : ''}${open?.message.id === m.id ? ' on' : ''}`}
            onClick={() => read(m)} onKeyDown={(e) => { if (e.key === 'Enter') read(m); }}>
            <button className={`star${m.starred ? ' on' : ''}`} aria-label={m.starred ? 'Unstar' : 'Star'}
              onClick={(e) => { e.stopPropagation(); change(m, { starred: !m.starred }); }}>{I.star()}</button>
            <div className="mail-row-main">
              <div className="mail-row-top">
                <span className="who">{m.box === 'sent' ? `To ${m.to.join(', ')}` : m.from}</span>
                <span className="hint">{when(m.created)}</span>
              </div>
              <div className="subj">{m.subject || '(no subject)'}</div>
              <div className="hint snip">{m.snippet}</div>
            </div>
          </div>
        ))}
      </section>
      <section className="mail-read">
        {draft ? (
          <Compose draft={draft} setDraft={setDraft} ask={ask} onSent={() => { setDraft(null); toast('Sent'); if (box === 'sent') loadList(); }} />
        ) : open ? (
          <div className="mail-open">
            <div className="row mail-actions">
              <button className="btn mail-back" onClick={() => setOpen(null)}>Back</button>
              <button className="btn" onClick={() => reply(open.message)}>Reply</button>
              {open.message.to.length > 1 && <button className="btn" onClick={() => reply(open.message, true)}>Reply all</button>}
              {open.message.box !== 'archive' && open.message.box !== 'sent' && open.message.box !== 'trash' &&
                <button className="btn" onClick={() => change(open.message, { box: 'archive' }, 'Archived')}>Archive</button>}
              {open.message.box === 'trash' &&
                <button className="btn" onClick={() => change(open.message, { box: open.message.from === me.name ? 'sent' : 'inbox' }, 'Restored')}>Restore</button>}
              {open.message.box === 'inbox' && <button className="btn" onClick={() => change(open.message, { unread: true })}>Mark unread</button>}
              <button className="btn" onClick={() => remove(open.message)}>{open.message.box === 'trash' ? 'Delete for good' : 'Delete'}</button>
              {open.message.from !== me.name && (
                <button className="btn" onClick={async () => {
                  try { await ask('/mail/blocks', { method: 'POST', body: JSON.stringify({ name: open.message.from }) }); toast(`You won't get mail from ${open.message.from} anymore`); }
                  catch (e: any) { toast(e.message); }
                }}>Block {open.message.from}</button>
              )}
            </div>
            <h2>{open.message.subject || '(no subject)'}</h2>
            {open.conversation.map((m) => (
              <article key={m.id} className="mail-msg">
                <header><strong>{m.from}</strong> <span className="hint">to {m.to.join(', ')} · {new Date(m.created * 1000).toLocaleString()}</span></header>
                <div className="mail-body">{m.body}</div>
              </article>
            ))}
          </div>
        ) : (
          <div className="empty">Pick a message, or write one.</div>
        )}
      </section>
    </div>
  );
}

function ClaimName({ ask, onDone }: { ask: (p: string, i?: RequestInit) => Promise<any>; onDone: (name: string) => void }) {
  const [name, setName] = useState('');
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const claim = async () => {
    setBusy(true); setErr('');
    try { onDone((await ask('/mail/name', { method: 'POST', body: JSON.stringify({ name }) })).name); }
    catch (e: any) { setErr(e.message); setBusy(false); }
  };
  return (
    <div className="mail"><div className="mail-claim">
      <h2>Mtrini Mail</h2>
      <p className="hint">Mail between Mtrini accounts: friends, your team, people testing your app. It can't send to Gmail or other email.</p>
      <label className="f" htmlFor="mailname">Pick your name. You can't change it later.</label>
      <div className="row" style={{ gap: 8 }}>
        <input id="mailname" className="t" value={name} autoFocus maxLength={30} placeholder="ayham"
          onChange={(e) => setName(e.target.value.toLowerCase())} onKeyDown={(e) => { if (e.key === 'Enter' && name) claim(); }} />
        <span className="hint mono">@mtrini</span>
      </div>
      {err && <p className="notice" role="alert">{err}</p>}
      <button className="btn primary" disabled={!name || busy} onClick={claim} style={{ marginTop: 12 }}>Claim {name ? `${name}@mtrini` : 'name'}</button>
    </div></div>
  );
}

function Compose({ draft, setDraft, ask, onSent }: {
  draft: { to: string; subject: string; body: string; reply_to?: string };
  setDraft: (d: any) => void; ask: (p: string, i?: RequestInit) => Promise<any>; onSent: () => void;
}) {
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const body = useRef<HTMLTextAreaElement>(null);
  useEffect(() => { if (draft.reply_to) body.current?.focus(); }, [draft.reply_to]);
  const send = async () => {
    setBusy(true); setErr('');
    try { await ask('/mail/send', { method: 'POST', body: JSON.stringify(draft) }); onSent(); }
    catch (e: any) { setErr(e.message); setBusy(false); }
  };
  return (
    <div className="mail-compose">
      <div className="row mail-actions">
        <button className="btn mail-back" onClick={() => setDraft(null)}>Back</button>
        <strong style={{ flex: 1 }}>{draft.reply_to ? 'Reply' : 'New message'}</strong>
        <button className="btn" onClick={() => setDraft(null)}>Discard</button>
        <button className="btn primary" disabled={busy || !draft.to.trim()} onClick={send}>{I.send()} Send</button>
      </div>
      <label className="f" htmlFor="mailto">To</label>
      <input id="mailto" className="t" value={draft.to} placeholder="Mtrini names, separated by commas"
        onChange={(e) => setDraft({ ...draft, to: e.target.value })} autoFocus={!draft.reply_to} />
      <label className="f" htmlFor="mailsubj">Subject</label>
      <input id="mailsubj" className="t" value={draft.subject} maxLength={200} onChange={(e) => setDraft({ ...draft, subject: e.target.value })} />
      <label className="f" htmlFor="mailbody">Message</label>
      <textarea id="mailbody" ref={body} className="t mail-text" value={draft.body}
        onChange={(e) => setDraft({ ...draft, body: e.target.value })}
        onKeyDown={(e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && draft.to.trim()) send(); }} />
      {err && <p className="notice" role="alert">{err}</p>}
    </div>
  );
}
