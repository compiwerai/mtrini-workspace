import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ago, api, listen, type Background, type Bot, type BotEvent, type FirstRun, type InboxItem, type Telegram, type Template } from './api';
import { BotView, MascotPicker, ModelPicker } from './BotView';
import { Avatar, Dialog, Icon, Rich } from './parts';
import { ImportRecipe, ShareCard } from './Share';

type View = { kind: 'inbox' } | { kind: 'bot'; id: string };
const waiting = (i: InboxItem) => i.kind === 'approval' && i.state === 'pending';
const CREW: [string, string, string][] = [['Atlas', '#5ad1e6', 'camel'], ['Scout', '#f0892b', 'fennec'], ['Sentinel', '#26b97a', 'owl'],
  ['Quill', '#8a5cf5', 'stork'], ['Bazaar', '#e5505b', 'cat'], ['Sage', '#e2b93b', 'tortoise'], ['Herald', '#4f8df7', 'parrot'], ['Patch', '#d86ad0', 'beetle']];

export default function BotsApp() {
  const [bots, setBots] = useState<Bot[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [hasBrowser, setHasBrowser] = useState(true);
  const [items, setItems] = useState<InboxItem[]>([]);
  const [view, setView] = useState<View>({ kind: 'inbox' });
  // Live events go to whoever subscribed, one by one. (Keeping only "the latest event" in state loses
  // all but the last when several arrive together.)
  const subs = useRef(new Set<(ev: BotEvent) => void>());
  const subscribe = useCallback((fn: (ev: BotEvent) => void) => { subs.current.add(fn); return () => { subs.current.delete(fn); }; }, []);
  const [creating, setCreating] = useState(false);
  const [importing, setImporting] = useState(false);
  const [firstRun, setFirstRun] = useState<FirstRun | null>(null);
  const firstBot = useRef('');
  const [telegram, setTelegram] = useState<Telegram | null>(null);
  const [showTelegram, setShowTelegram] = useState(false);
  const [background, setBackground] = useState<Background | null>(null);
  const [showBackground, setShowBackground] = useState(false);
  const [toast, setToast] = useState<{ text: string; bad?: boolean } | null>(null);
  const toastTimer = useRef<number>();

  const notify = useCallback((text: string, bad?: boolean) => {
    setToast({ text, bad });
    window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), bad ? 7000 : 4000);
  }, []);
  const loadBots = useCallback(() => api.bots().then((r) => { setBots(r.bots); setHasBrowser(r.browser); setLoaded(true); }).catch(() => setLoaded(true)), []);
  const loadInbox = useCallback(() => api.inbox().then((r) => setItems(r.items)).catch(() => {}), []);

  useEffect(() => {
    loadBots(); loadInbox();
    api.telegram().then(setTelegram).catch(() => {});
    api.background().then(setBackground).catch(() => {});
    // First launch: a starter bot does a real job right away, on the free model, and you watch it happen.
    api.firstRun().then(async (f) => {
      if (f.state === 'none' || f.state === 'seen' || !f.bot) return;
      firstBot.current = f.bot;
      setView({ kind: 'bot', id: f.bot });
      setFirstRun(f.state === 'pending' ? await api.startFirstRun() : f);
    }).catch(() => {});
    const close = listen((ev) => {
      subs.current.forEach((fn) => fn(ev));
      if ((ev.type === 'message' || ev.type === 'state') && ev.bot === firstBot.current) api.firstRun().then(setFirstRun).catch(() => {});
      if (ev.type === 'bots' || ev.type === 'hello') loadBots();
      if (ev.type === 'state') setBots((all) => all.map((b) => (b.id === ev.bot ? { ...b, state: { status: ev.status, label: ev.label, since: ev.since } } : b)));
      if (ev.type === 'inbox') { loadInbox(); loadBots(); }
    });
    const poll = window.setInterval(() => { loadBots(); loadInbox(); }, 30000);  // a safety net if the live stream drops
    return () => { close(); window.clearInterval(poll); };
  }, [loadBots, loadInbox]);

  const unread = items.filter((i) => !i.read).length;
  const current = view.kind === 'bot' ? bots.find((b) => b.id === view.id) : undefined;
  useEffect(() => { document.title = unread ? `(${unread}) Mtrini Bots` : 'Mtrini Bots'; }, [unread]);

  return (
    <div className="app">
      <aside className="side">
        <div className="brand"><img src="/bots.png" alt="" /><b>Mtrini Bots</b></div>
        <button className={`navrow ${view.kind === 'inbox' ? 'on' : ''}`} title="Inbox" onClick={() => setView({ kind: 'inbox' })}>
          <Icon name="inbox" /><span className="grow">Inbox</span>{unread ? <span className="count" aria-label={`${unread} unread`}>{unread}</span> : null}
        </button>
        <div className="sec"><span>Bots</span><button aria-label="New bot" title="New bot" onClick={() => setCreating(true)}><Icon name="plus" /></button></div>
        <div className="botlist">
          {bots.map((b) => {
            const busy = b.state.status === 'working' || b.state.status === 'queued';
            return (
              <button key={b.id} className={`navrow ${view.kind === 'bot' && view.id === b.id ? 'on' : ''}`} title={`${b.name}${b.role ? ` · ${b.role}` : ''}`}
                onClick={() => setView({ kind: 'bot', id: b.id })}>
                <Avatar bot={b} status={b.state.status} />
                <span className="grow">{b.name}</span>
                {b.waiting ? <span className="count warn" title="Waiting for your approval">{b.waiting}</span>
                  : <span className="mono">{b.paused ? 'paused' : busy ? 'working' : ''}</span>}
              </button>
            );
          })}
        </div>
        <div className="sidefoot">
          <button className="navrow" title="Always on" aria-label="Always on" onClick={() => { setShowBackground(true); api.background().then(setBackground).catch(() => {}); }}>
            <Icon name="clock" /><span className="grow">Always on</span><span className="mono">{background?.keepRunning ? 'on' : 'off'}</span>
          </button>
          <button className="navrow" title="Telegram" aria-label="Telegram" onClick={() => setShowTelegram(true)}>
            <Icon name="phone" /><span className="grow">Telegram</span><span className="mono">{telegram?.paired ? 'on' : 'off'}</span>
          </button>
        </div>
      </aside>

      <main className="main">
        {view.kind === 'inbox' || !current ? (
          <Inbox items={items} bots={bots} loaded={loaded} onNew={() => setCreating(true)} onImport={() => setImporting(true)} reload={() => { loadInbox(); loadBots(); }}
            openBot={(id) => setView({ kind: 'bot', id })} notify={notify} />
        ) : (
          <BotView bot={current} subscribe={subscribe} hasBrowser={hasBrowser} onChanged={loadBots} notify={notify}
            firstRun={firstRun} onFirstRun={setFirstRun}
            onDeleted={() => { setView({ kind: 'inbox' }); loadBots(); loadInbox(); notify('Bot deleted'); }} />
        )}
      </main>

      {creating ? <NewBot onClose={() => setCreating(false)} onImport={() => { setCreating(false); setImporting(true); }}
        onCreated={(b) => { setCreating(false); loadBots().then(() => setView({ kind: 'bot', id: b.id })); }} /> : null}
      {importing ? <ImportRecipe onClose={() => setImporting(false)}
        onImported={(b) => { setImporting(false); notify(`${b.name} is ready. Its routines are off until you switch them on.`); loadBots().then(() => setView({ kind: 'bot', id: b.id })); }} /> : null}
      {showBackground ? <BackgroundDialog status={background} onChange={setBackground} onClose={() => setShowBackground(false)} notify={notify} /> : null}
      {showTelegram ? <TelegramDialog status={telegram} bots={bots} onChange={setTelegram} onClose={() => setShowTelegram(false)} /> : null}
      {toast ? <div className={`toast ${toast.bad ? 'bad' : ''}`} role="status">{toast.text}</div> : null}
    </div>
  );
}

function Inbox({ items, bots, loaded, onNew, onImport, reload, openBot, notify }: {
  items: InboxItem[]; bots: Bot[]; loaded: boolean; onNew: () => void; onImport: () => void; reload: () => void; openBot: (id: string) => void;
  notify: (t: string, bad?: boolean) => void;
}) {
  const [openId, setOpenId] = useState<string | null>(null);
  const [sharing, setSharing] = useState<InboxItem | null>(null);
  const need = items.filter(waiting);
  const rest = items.filter((i) => !waiting(i));
  const open = items.find((i) => i.id === openId) || null;
  const who = (i: InboxItem) => ({ name: i.botName, color: i.botColor || bots.find((b) => b.id === i.bot)?.color || '#5ad1e6',
    mascot: i.botMascot || bots.find((b) => b.id === i.bot)?.mascot });
  const hasRead = rest.some((i) => i.read);
  const hasUnread = rest.some((i) => !i.read);

  const pick = (i: InboxItem) => {
    setOpenId(i.id);
    if (!i.read && !waiting(i)) api.markRead(i.bot, i.id, true).then(reload).catch(() => {});
  };
  const answer = async (i: InboxItem, decision: 'allow' | 'deny') => {
    try { await api.resolve(i.bot, i.id, decision); notify(decision === 'allow' ? `Approved. ${i.botName} carries on.` : `Denied. ${i.botName} will not do it.`); }
    catch (e: any) { notify(e.message, true); }
    reload();
  };

  const row = (i: InboxItem) => (
    <button key={i.id} className={`mailrow ${waiting(i) ? 'need' : i.read ? '' : 'unread'} ${open?.id === i.id ? 'on' : ''}`} onClick={() => pick(i)}>
      <span className="mark" />
      <Avatar bot={who(i)} />
      <span className="t"><b>{i.title}</b><small>{i.botName} · {waiting(i) ? 'needs your answer' : i.kind === 'approval' ? (i.state === 'approved' ? 'you approved' : i.state === 'denied' ? 'you denied' : 'closed') : i.body.replace(/[#*`\n]+/g, ' ').trim().slice(0, 80)}</small></span>
      <time>{ago(i.ts)}</time>
    </button>
  );

  if (loaded && bots.length === 0) {
    return (
      <>
        <header className="head"><div className="grow"><h1>Inbox</h1></div></header>
        <div className="pane">
          <div className="intro">
            <div className="crew">{CREW.map(([name, color, mascot]) => <Avatar key={name} bot={{ name, color, mascot }} size="lg" />)}</div>
            <h2>Bots that keep working, and ask before they act</h2>
            <p>Each bot has a job, a folder and a memory of its own. It reports here.</p>
            <ul>
              <li><b>Routines</b>Work on a schedule: a morning briefing, a page to watch, news on a topic.</li>
              <li><b>Own browser</b>It reads and clicks through sites. You sign in yourself, once.</li>
              <li><b>Approvals</b>Sending, buying or deleting waits here for your yes.</li>
              <li><b>Yours</b>Runs on this computer. Files and memory are plain text you can open.</li>
            </ul>
            <div className="acts" style={{ marginTop: 0 }}>
              <button className="btn primary tall" onClick={onNew}><Icon name="plus" />New bot</button>
              <button className="btn ghost tall" onClick={onImport}>Add from a recipe</button>
            </div>
          </div>
        </div>
      </>
    );
  }

  return (
    <>
      <header className="head">
        <div className="grow"><h1>Inbox</h1><span className="sub">{need.length ? `${need.length} waiting for you` : hasUnread ? 'New reports' : 'All read'}</span></div>
        {hasUnread ? <button className="btn ghost" onClick={() => api.readAll().then(reload)}>Mark all read</button> : null}
        {hasRead ? <button className="btn ghost" onClick={() => { setOpenId(null); api.clearInbox().then(reload); }}>Clear read</button> : null}
      </header>
      <div className={`pane mail ${open ? 'reading' : ''}`}>
        <div className="maillist">
          {items.length === 0 ? <p className="blank">Nothing yet. Reports from routines and anything that needs your yes will land here.</p> : null}
          {need.length ? <><div className="mailgroup">Needs you</div>{need.map(row)}</> : null}
          {rest.length ? <><div className="mailgroup">Reports</div>{rest.map(row)}</> : null}
        </div>
        <div className="reader">
          {open ? (
            <article className="letter">
              <button className="btn ghost back" onClick={() => setOpenId(null)}>← Inbox</button>
              <h2>{open.title}</h2>
              <div className="by">
                <Avatar bot={who(open)} /><b>{open.botName}</b><span>{new Date(open.ts * 1000).toLocaleString(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}</span>
                {open.state === 'approved' ? <span className="verdict ok">approved</span> : null}
                {open.state === 'denied' ? <span className="verdict no">denied</span> : null}
                {open.state === 'expired' ? <span className="verdict off">closed</span> : null}
                {open.kind === 'error' ? <span className="verdict no">failed</span> : null}
              </div>
              {open.kind === 'approval' ? (
                <div className={`ask ${waiting(open) ? '' : 'done'}`}>
                  <p>{waiting(open) ? `${open.botName} stopped here and is waiting. Nothing has been done yet.` : 'What was asked:'}</p>
                  <pre>{open.body}</pre>
                  {waiting(open) ? (
                    <div className="acts" style={{ marginTop: 0 }}>
                      <button className="btn primary tall" onClick={() => answer(open, 'allow')}><Icon name="check" />Approve</button>
                      <button className="btn tall" onClick={() => answer(open, 'deny')}><Icon name="x" />Deny</button>
                    </div>
                  ) : null}
                </div>
              ) : <Rich text={open.body} />}
              <div className="acts">
                {open.kind !== 'approval' && open.kind !== 'error' ? <button className="btn" onClick={() => setSharing(open)}><Icon name="share" />Share as card</button> : null}
                <button className="btn" onClick={() => openBot(open.bot)}>Open {open.botName}</button>
                {!waiting(open) && open.read ? <button className="btn ghost" onClick={() => { api.markRead(open.bot, open.id, false).then(reload); setOpenId(null); }}>Mark unread</button> : null}
              </div>
            </article>
          ) : items.length ? <p className="blank">Pick a report to read it.</p> : null}
        </div>
      </div>
      {sharing ? (() => {
        const b = bots.find((x) => x.id === sharing.bot);
        const face = { name: sharing.botName, role: b?.role || '', color: who(sharing).color, mascot: who(sharing).mascot || 'camel', provider: b?.provider || '' };
        return <ShareCard bot={face} text={sharing.body} title={sharing.title} notify={notify} onClose={() => setSharing(null)} />;
      })() : null}
    </>
  );
}

function NewBot({ onClose, onCreated, onImport }: { onClose: () => void; onCreated: (b: Bot) => void; onImport: () => void }) {
  const [templates, setTemplates] = useState<Template[]>([]);
  const [tpl, setTpl] = useState('chief');
  const [form, setForm] = useState({ name: '', role: '', instructions: '', provider: 'free', model: '', color: '#5ad1e6', mascot: 'camel' });
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    api.templates().then((r) => { setTemplates(r.templates); const t = r.templates.find((x) => x.key === 'chief'); if (t) setForm((f) => ({ ...f, name: t.name, role: t.role, instructions: t.instructions, mascot: t.mascot || f.mascot })); }).catch(() => {});
  }, []);
  const pick = (t: Template) => { setTpl(t.key); setForm({ ...form, name: t.name, role: t.role, instructions: t.instructions, mascot: t.mascot || form.mascot }); };
  const create = async () => {
    setBusy(true); setErr('');
    try { onCreated(await api.create({ ...form, template: tpl })); } catch (e: any) { setErr(e.message); setBusy(false); }
  };
  const chosen = templates.find((t) => t.key === tpl);
  return (
    <Dialog title="New bot" intro="Pick a job to start from. Everything can be changed later." onClose={onClose}>
      <div className="jobs" role="group" aria-label="Job">
        {templates.map((t) => (
          <button key={t.key} type="button" className={tpl === t.key ? 'on' : ''} aria-pressed={tpl === t.key} onClick={() => pick(t)}>{t.role || 'Blank'}</button>
        ))}
      </div>
      <p className="jobnote">{chosen?.routines.length ? `Comes with a routine: ${chosen.routines.join(', ')}` : chosen ? 'No routine to start with' : ''}</p>
      <div className="row">
        <div className="field"><label htmlFor="n-name">Name</label><input id="n-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Atlas" /></div>
        <div className="field"><label htmlFor="n-role">Role</label><input id="n-role" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })} placeholder="Chief of staff" /></div>
      </div>
      <div className="field"><label htmlFor="n-instr">What is it for?</label>
        <textarea id="n-instr" value={form.instructions} onChange={(e) => setForm({ ...form, instructions: e.target.value })} placeholder="What this bot is for, and how you like things done." /></div>
      <ModelPicker provider={form.provider} model={form.model} onChange={(provider, model) => setForm((f) => ({ ...f, provider, model }))} />
      <div className="field">
        <span className="label">Mascot</span>
        <MascotPicker mascot={form.mascot} color={form.color} onChange={(mascot, color) => setForm({ ...form, mascot, color })} />
      </div>
      {err ? <div className="err" role="alert">{err}</div> : null}
      <div className="foot"><button className="btn ghost tall" style={{ marginRight: 'auto' }} onClick={onImport}>From a recipe</button>
        <button className="btn ghost tall" onClick={onClose}>Cancel</button><button className="btn primary tall" disabled={busy || !form.name.trim()} onClick={create}>Create bot</button></div>
    </Dialog>
  );
}

function BackgroundDialog({ status, onChange, onClose, notify }: { status: Background | null; onChange: (b: Background) => void; onClose: () => void; notify: (t: string, bad?: boolean) => void }) {
  const [err, setErr] = useState('');
  const set = async (patch: { keepRunning?: boolean; autostart?: boolean }) => {
    setErr('');
    try { onChange(await api.saveBackground(patch)); } catch (e: any) { setErr(e.message); }
  };
  const quit = async () => { try { await api.quit(); notify('Bots stopped. You can close this window.'); onClose(); } catch (e: any) { setErr(e.message); } };
  return (
    <Dialog title="Always on" intro="Let your bots keep their schedule when you are not looking." onClose={onClose}>
      <div className="table">
        <div className="item">
          <button className={`switch ${status?.keepRunning ? 'on' : ''}`} role="switch" aria-checked={!!status?.keepRunning} aria-label="Keep running when I close the window"
            onClick={() => set({ keepRunning: !status?.keepRunning })} />
          <div className="grow"><b>Keep running when I close the window</b>
            <small className="last">The app stays in the background while a routine is switched on or Telegram is connected.</small></div>
        </div>
        <div className="item">
          <button className={`switch ${status?.autostart ? 'on' : ''}`} role="switch" aria-checked={!!status?.autostart} aria-label="Start when I sign in"
            disabled={!status?.installed} onClick={() => set({ autostart: !status?.autostart })} />
          <div className="grow"><b>Start when I sign in to this computer</b>
            <small className="last">{status?.installed ? 'Starts quietly, with no window, so routines run from the moment you sign in.' : 'Works in the installed app, not in this development copy.'}</small></div>
        </div>
      </div>
      <p className="hint" style={{ marginTop: 16 }}>
        {status?.keepRunning && !status.hasWork ? 'Nothing to keep running yet: switch on a routine or connect Telegram. ' : ''}
        Bots run while this computer is on and awake. They can't run while it is off: that would need a server, and Mtrini Bots runs on your own machine.
      </p>
      {err ? <div className="err" role="alert">{err}</div> : null}
      <div className="foot">
        {status?.desktop ? <button className="btn danger tall" onClick={quit}>Stop bots and quit</button> : null}
        <button className="btn tall" onClick={onClose}>Done</button>
      </div>
    </Dialog>
  );
}

function TelegramDialog({ status, bots, onChange, onClose }: { status: Telegram | null; bots: Bot[]; onChange: (t: Telegram) => void; onClose: () => void }) {
  const [token, setToken] = useState('');
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!status?.connected || status.paired) return;
    const t = window.setInterval(() => api.telegram().then(onChange).catch(() => {}), 3000);  // wait for the pairing message
    return () => window.clearInterval(t);
  }, [status?.connected, status?.paired, onChange]);
  const connect = async () => {
    setBusy(true); setErr('');
    try { onChange(await api.telegramConnect(token)); setToken(''); } catch (e: any) { setErr(e.message); }
    setBusy(false);
  };
  return (
    <Dialog title="Telegram" intro="Text your bots from your phone, get their reports there, and approve or deny with one tap." onClose={onClose}>
      {!status?.connected ? (
        <>
          <ol className="howto">
            <li>In Telegram, open a chat with <b>@BotFather</b> and send <code>/newbot</code>.</li>
            <li>Pick a name. BotFather gives you a token.</li>
            <li>Paste the token here. It is kept in this computer's keychain.</li>
          </ol>
          <div className="field"><label htmlFor="t-token">Bot token</label>
            <input id="t-token" type="password" autoComplete="off" value={token} onChange={(e) => setToken(e.target.value)} placeholder="Paste the token from BotFather" /></div>
          {err ? <div className="err" role="alert">{err}</div> : null}
          <div className="foot"><button className="btn ghost tall" onClick={onClose}>Close</button><button className="btn primary tall" disabled={busy || !token.trim()} onClick={connect}>Connect</button></div>
        </>
      ) : !status.paired ? (
        <>
          <p className="hint">Send this code to {status.username ? <b>@{status.username}</b> : 'your bot'} in Telegram. Only the chat that sends it is ever answered.</p>
          <div className="code" aria-label="Pairing code">{status.pairCode}</div>
          {status.error ? <div className="err" role="alert">{status.error}</div> : <p className="hint">Waiting for your message</p>}
          <div className="foot"><button className="btn danger tall" onClick={() => api.telegramDisconnect().then(onChange)}>Disconnect</button><button className="btn tall" onClick={onClose}>Close</button></div>
        </>
      ) : (
        <>
          <div className="note">Connected{status.username ? <> to <b>@{status.username}</b></> : null}. Write a message there and your default bot answers. Start it with @name to reach another bot.</div>
          <div className="field" style={{ marginTop: 16 }}><label htmlFor="t-default">Default bot</label>
            <select id="t-default" value={status.defaultBot || bots[0]?.id || ''} onChange={(e) => api.telegramDefault(e.target.value).then(onChange).catch((x) => setErr(x.message))}>
              {bots.map((b) => <option key={b.id} value={b.id}>{b.name}</option>)}
            </select></div>
          {status.error ? <div className="err" role="alert">{status.error}</div> : null}
          {err ? <div className="err" role="alert">{err}</div> : null}
          <div className="foot"><button className="btn danger tall" onClick={() => api.telegramDisconnect().then(onChange)}>Disconnect</button><button className="btn tall" onClick={onClose}>Close</button></div>
        </>
      )}
    </Dialog>
  );
}
