import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ago, api, until, type Bot, type BotEvent, type FirstRun, type Message, type Provider, type Routine } from './api';
import { MASCOT_NAMES } from './mascots';
import { Avatar, Dialog, Icon, Rich } from './parts';
import { CardCanvas, cardData, ShareCard, ShareRecipe } from './Share';

type Tab = 'chat' | 'routines' | 'memory' | 'files' | 'settings';
const DAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
const STARTERS = ['What can you do for me?', 'Search the web for today\'s AI news and give me 5 links', 'Remember that I prefer short answers'];

type Subscribe = (fn: (ev: BotEvent) => void) => () => void;
const shareable = (m: Message) => m.role === 'assistant' && !m.error && !m.stopped && !m.approval && m.content.trim().length > 30;

export function BotView({ bot, subscribe, hasBrowser, onChanged, onDeleted, notify, firstRun, onFirstRun }: {
  bot: Bot; subscribe: Subscribe; hasBrowser: boolean; onChanged: () => void; onDeleted: () => void;
  notify: (text: string, bad?: boolean) => void; firstRun?: FirstRun | null; onFirstRun?: (f: FirstRun) => void;
}) {
  const [tab, setTab] = useState<Tab>('chat');
  useEffect(() => { setTab('chat'); }, [bot.id]);
  const busy = bot.state.status === 'working' || bot.state.status === 'queued';
  const status = bot.paused ? 'paused' : busy ? 'working' : bot.state.status === 'waiting' ? 'waiting for you' : 'ready';

  const showBrowser = async () => {
    try { await api.showBrowser(bot.id); notify(`${bot.name}'s browser is open. Sign in there if a site needs it, then close the window.`); }
    catch (e: any) { notify(e.message, true); }
  };
  const togglePause = async () => {
    try { await api.update(bot.id, { paused: !bot.paused }); onChanged(); } catch (e: any) { notify(e.message, true); }
  };

  return (
    <>
      <header className="head">
        <Avatar bot={bot} size="md" />
        <div className="grow">
          <h1>{bot.name}</h1>
          <span className="sub">{bot.role || 'Assistant'}</span>
          <span className={`status ${busy ? 'working' : bot.state.status === 'waiting' ? 'waiting' : ''}`}>{status}</span>
        </div>
        {hasBrowser ? <button className="btn ghost" onClick={showBrowser} title="Open this bot's own browser so you can sign in to a site"><Icon name="globe" />Show browser</button> : null}
        <button className="btn ghost" onClick={togglePause}><Icon name={bot.paused ? 'play' : 'pause'} />{bot.paused ? 'Resume' : 'Pause'}</button>
      </header>
      <nav className="tabs" role="tablist">
        {(['chat', 'routines', 'memory', 'files', 'settings'] as Tab[]).map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? 'on' : ''} onClick={() => setTab(t)}>
            {t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </nav>
      <div className="pane">
        {tab === 'chat' ? <Chat bot={bot} subscribe={subscribe} notify={notify} firstRun={firstRun?.bot === bot.id ? firstRun : null} onFirstRun={onFirstRun} /> : null}
        {tab === 'routines' ? <Routines bot={bot} notify={notify} onChanged={onChanged} /> : null}
        {tab === 'memory' ? <Memory bot={bot} notify={notify} /> : null}
        {tab === 'files' ? <Files bot={bot} /> : null}
        {tab === 'settings' ? <Settings bot={bot} notify={notify} onChanged={onChanged} onDeleted={onDeleted} /> : null}
      </div>
    </>
  );
}

function Chat({ bot, subscribe, notify, firstRun, onFirstRun }: {
  bot: Bot; subscribe: Subscribe; notify: (t: string, bad?: boolean) => void; firstRun?: FirstRun | null; onFirstRun?: (f: FirstRun) => void;
}) {
  const [msgs, setMsgs] = useState<Message[]>([]);
  const [sharing, setSharing] = useState<Message | null>(null);
  const first = firstRun && firstRun.state !== 'seen' && firstRun.state !== 'none' ? firstRun : null;
  const firstReply = first?.state === 'done' ? first.message : undefined;
  const firstAsk = firstReply ? [...msgs].reverse().find((m) => m.role === 'user' && m.ts <= firstReply.ts) : undefined;
  const took = firstReply && firstAsk ? Math.max(1, Math.round(firstReply.ts - firstAsk.ts)) : 0;
  const firstDone = () => api.firstRunSeen().then((f) => onFirstRun?.(f)).catch(() => {});
  const firstAgain = () => api.startFirstRun().then((f) => onFirstRun?.(f)).catch((e) => notify(e.message, true));
  const [text, setText] = useState('');
  const [live, setLive] = useState('');
  const end = useRef<HTMLDivElement>(null);
  const working = bot.state.status === 'working' || bot.state.status === 'queued';

  const load = useCallback(() => { api.conversation(bot.id).then((r) => setMsgs(r.messages)).catch(() => {}); }, [bot.id]);
  useEffect(() => { setMsgs([]); setLive(''); load(); }, [load]);
  useEffect(() => subscribe((ev) => {
    if (!('bot' in ev) || ev.bot !== bot.id) return;
    if (ev.type === 'message') { setMsgs((m) => (m.some((x) => x.id === ev.message.id) ? m : [...m, ev.message])); setLive(''); }
    if (ev.type === 'live') setLive(ev.text);
    if (ev.type === 'state' && ev.status !== 'working' && ev.status !== 'queued') load();  // the turn ended: make sure nothing was missed
  }), [subscribe, bot.id, load]);
  useEffect(() => { end.current?.scrollIntoView?.({ block: 'end' }); }, [msgs, live, bot.state.label]);

  const send = async (value: string) => {
    const t = value.trim();
    if (!t || working) return;
    setText('');
    try { await api.send(bot.id, t); } catch (e: any) { notify(e.message, true); setText(t); }
  };

  return (
    <div className="chat">
      <div className="msgs">
        {first ? (
          <div className={`firstrun ${first.state}`} role="status">
            {first.state === 'done' ? <><b>{took ? `Done in ${took} ${took === 1 ? 'second' : 'seconds'}.` : 'Done.'}</b> On the free built-in model: no key, no setup.</>
              : first.state === 'failed' ? <><b>The free model could not answer just now.</b> <button className="linkbtn" onClick={firstAgain}>Try again</button></>
              : <><b>{bot.name}'s first job.</b> It runs on the free built-in model: no key, no setup.</>}
          </div>
        ) : null}
        {msgs.length === 0 && !working ? (
          <div className="hello">
            <p>{bot.name} keeps its notes in its own folder, remembers what you tell it, and asks before it acts for you. Try:</p>
            {STARTERS.map((s) => <button key={s} onClick={() => send(s)}>{s}</button>)}
          </div>
        ) : null}
        {msgs.map((m) => m.role === 'user' ? (
          <div key={m.id} className="msg user">
            <div className={`said ${m.routine ? 'auto' : ''}`}>{m.content}</div>
            <div className="when">{m.routine ? 'on schedule' : m.source === 'telegram' ? 'you, from Telegram' : 'you'} · {ago(m.ts)}</div>
          </div>
        ) : (
          <div key={m.id} className="msg bot">
            {m.steps && m.steps.length ? (
              <details className="trail">
                <summary><Icon name="chevron" />{m.steps.length} {m.steps.length === 1 ? 'step' : 'steps'}</summary>
                <ol>{m.steps.map((s, i) => <li key={i} className={s.ok === false ? 'failed' : ''}>{s.label}</li>)}</ol>
              </details>
            ) : null}
            <Rich text={m.content} className={`text ${m.error ? 'bad' : ''}`} />
            <div className="when">{bot.name} · {ago(m.ts)}{shareable(m) ? <> · <button className="linkbtn" onClick={() => setSharing(m)}>Share as card</button></> : null}</div>
            {firstReply?.id === m.id ? (
              <div className="firstcard">
                <CardCanvas data={cardData(bot, m.content).data} />
                <div className="acts">
                  <button className="btn primary tall" onClick={() => setSharing(m)}><Icon name="share" />Share this card</button>
                  <button className="btn ghost tall" onClick={firstDone}>Done</button>
                </div>
              </div>
            ) : null}
          </div>
        ))}
        {working ? <div className="live" role="status">{bot.state.label || 'Working'}</div> : null}
        {bot.state.status === 'waiting' ? <div className="live waiting" role="status">Waiting for your answer in the inbox</div> : null}
        <div ref={end} />
      </div>
      {sharing ? <ShareCard bot={bot} text={sharing.content} title={typeof sharing.routine === 'string' ? sharing.routine : ''} notify={notify}
        onClose={() => setSharing(null)} /> : null}
      <div className="composer">
        <div className="box">
          <textarea rows={1} value={text} placeholder={bot.paused ? `${bot.name} is paused` : `Message ${bot.name}`} disabled={bot.paused}
            aria-label={`Message ${bot.name}`} onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(text); } }} />
          {working
            ? <button className="btn tall" onClick={() => api.stop(bot.id).catch((e) => notify(e.message, true))}><Icon name="stop" />Stop</button>
            : <button className="btn primary tall iconbtn" style={{ width: 32 }} aria-label="Send" disabled={!text.trim() || bot.paused} onClick={() => send(text)}><Icon name="send" /></button>}
        </div>
      </div>
    </div>
  );
}

const BLANK: Partial<Routine> = { title: '', prompt: '', kind: 'daily', time: '09:00', minutes: 60, days: [0, 1, 2, 3, 4], enabled: true };

function Routines({ bot, notify, onChanged }: { bot: Bot; notify: (t: string, bad?: boolean) => void; onChanged: () => void }) {
  const [items, setItems] = useState<Routine[]>([]);
  const [edit, setEdit] = useState<Partial<Routine> | null>(null);
  const [err, setErr] = useState('');
  const load = useCallback(() => { api.routines(bot.id).then((r) => setItems(r.routines)).catch(() => {}); }, [bot.id]);
  useEffect(load, [load]);

  const save = async () => {
    if (!edit) return;
    try { await api.saveRoutine(bot.id, edit); setEdit(null); setErr(''); load(); onChanged(); } catch (e: any) { setErr(e.message); }
  };
  const toggle = async (r: Routine) => { try { await api.saveRoutine(bot.id, { ...r, enabled: !r.enabled }); load(); } catch (e: any) { notify(e.message, true); } };
  const run = async (r: Routine) => { try { await api.runRoutine(bot.id, r.id); notify(`${bot.name} started "${r.title}". The result lands in the inbox.`); } catch (e: any) { notify(e.message, true); } };
  const remove = async (r: Routine) => { await api.removeRoutine(bot.id, r.id).catch(() => {}); load(); onChanged(); };

  return (
    <div className="wrap">
      <p className="lead">Work {bot.name} does on a schedule while Mtrini Bots is open. Each run reports to your inbox.</p>
      <div className="table">
        {items.map((r) => (
          <div className="item" key={r.id}>
            <button className={`switch ${r.enabled ? 'on' : ''}`} role="switch" aria-checked={r.enabled} aria-label={`${r.title} enabled`} onClick={() => toggle(r)} />
            <div className="grow">
              <b>{r.title}</b>
              <small>{r.when}{r.enabled ? ` · next ${until(r.nextRun)}` : ' · off'}{r.lastRun ? ` · last ran ${ago(r.lastRun)}` : ''}</small>
              {r.lastResult ? <small className="last">{r.lastResult}</small> : null}
            </div>
            <button className="btn ghost" onClick={() => run(r)}>Run now</button>
            <button className="btn ghost" onClick={() => { setEdit({ ...r }); setErr(''); }}>Edit</button>
            <button className="btn ghost iconbtn" aria-label={`Delete ${r.title}`} onClick={() => remove(r)}><Icon name="trash" /></button>
          </div>
        ))}
      </div>
      <div className="bar" style={{ marginTop: 16 }}>
        <button className="btn" onClick={() => { setEdit({ ...BLANK }); setErr(''); }}><Icon name="plus" />New routine</button>
        {items.length === 0 ? <span className="hint">None yet: every morning, every few hours, or on chosen days.</span> : null}
      </div>
      {edit ? (
        <Dialog title={edit.id ? 'Edit routine' : 'New routine'} intro={`What should ${bot.name} do, and when?`} onClose={() => setEdit(null)}>
          <div className="field"><label htmlFor="r-title">Name</label>
            <input id="r-title" value={edit.title || ''} onChange={(e) => setEdit({ ...edit, title: e.target.value })} placeholder="Morning briefing" /></div>
          <div className="field"><label htmlFor="r-prompt">What to do</label>
            <textarea id="r-prompt" value={edit.prompt || ''} onChange={(e) => setEdit({ ...edit, prompt: e.target.value })}
              placeholder="Search the web for news on my topics and report only what is new." /></div>
          <div className="row">
            <div className="field"><label htmlFor="r-kind">Repeat</label>
              <select id="r-kind" value={edit.kind} onChange={(e) => setEdit({ ...edit, kind: e.target.value as Routine['kind'] })}>
                <option value="daily">Every day</option><option value="weekly">On chosen days</option><option value="interval">Every few minutes or hours</option>
              </select></div>
            {edit.kind === 'interval'
              ? <div className="field"><label htmlFor="r-min">Every (minutes)</label>
                <input id="r-min" type="number" min={5} value={edit.minutes ?? 60} onChange={(e) => setEdit({ ...edit, minutes: Number(e.target.value) })} /></div>
              : <div className="field"><label htmlFor="r-time">At</label>
                <input id="r-time" type="time" value={edit.time || '09:00'} onChange={(e) => setEdit({ ...edit, time: e.target.value })} /></div>}
          </div>
          {edit.kind === 'weekly' ? (
            <div className="field"><span className="label">Days</span>
              <div className="days">{DAYS.map((d, i) => {
                const on = (edit.days || []).includes(i);
                return <button key={d} type="button" className={on ? 'on' : ''} aria-pressed={on}
                  onClick={() => setEdit({ ...edit, days: on ? (edit.days || []).filter((x) => x !== i) : [...(edit.days || []), i] })}>{d}</button>;
              })}</div></div>
          ) : null}
          {err ? <div className="err" role="alert">{err}</div> : null}
          <div className="foot"><button className="btn ghost" onClick={() => setEdit(null)}>Cancel</button><button className="btn primary" onClick={save}>Save routine</button></div>
        </Dialog>
      ) : null}
    </div>
  );
}

function Memory({ bot, notify }: { bot: Bot; notify: (t: string, bad?: boolean) => void }) {
  const [text, setText] = useState('');
  const [saved, setSaved] = useState('');
  useEffect(() => { api.memory(bot.id).then((r) => { setText(r.text); setSaved(r.text); }).catch(() => {}); }, [bot.id]);
  const save = async () => { try { await api.saveMemory(bot.id, text); setSaved(text); notify('Memory saved'); } catch (e: any) { notify(e.message, true); } };
  return (
    <div className="wrap">
      <p className="lead">What {bot.name} keeps between conversations. It is a plain text file: read it, fix it, or delete lines. Secrets are refused.</p>
      <textarea className="memory" aria-label={`${bot.name}'s memory`} value={text} onChange={(e) => setText(e.target.value)}
        placeholder={`Nothing yet. Tell ${bot.name} something worth remembering, or write it here.`} />
      <div className="foot" style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 12 }}>
        <button className="btn primary" disabled={text === saved} onClick={save}>Save memory</button>
      </div>
    </div>
  );
}

function Files({ bot }: { bot: Bot }) {
  const [files, setFiles] = useState<{ path: string; size: number; modified: number }[]>([]);
  const [open, setOpen] = useState<{ path: string; text: string; binary?: boolean } | null>(null);
  useEffect(() => { setOpen(null); api.files(bot.id).then((r) => setFiles(r.files)).catch(() => {}); }, [bot.id]);
  if (files.length === 0) {
    return <p className="blank">Nothing in {bot.name}'s folder yet. Notes, drafts and results it writes show up here. On this computer: <span className="mono">{bot.folder}</span></p>;
  }
  return (
    <div className="split">
      <div className="list">
        {files.map((f) => (
          <button key={f.path} className={`filerow ${open?.path === f.path ? 'on' : ''}`} onClick={() => api.file(bot.id, f.path).then(setOpen).catch(() => {})}>
            {f.path}<small>{f.size < 1024 ? `${f.size} B` : `${Math.round(f.size / 1024)} KB`} · {ago(f.modified)}</small>
          </button>
        ))}
      </div>
      <div className="view">
        {open ? (open.binary ? <p className="hint">This file is not text. Open it from {bot.folder}</p> : <pre className="file">{open.text}</pre>)
          : <p className="hint">Pick a file to read it. Folder: {bot.folder}</p>}
      </div>
    </div>
  );
}

function Settings({ bot, notify, onChanged, onDeleted }: { bot: Bot; notify: (t: string, bad?: boolean) => void; onChanged: () => void; onDeleted: () => void }) {
  const [form, setForm] = useState({ name: bot.name, role: bot.role, instructions: bot.instructions, provider: bot.provider, model: bot.model, color: bot.color, mascot: bot.mascot });
  const [confirm, setConfirm] = useState(false);
  const [recipe, setRecipe] = useState(false);
  useEffect(() => { setForm({ name: bot.name, role: bot.role, instructions: bot.instructions, provider: bot.provider, model: bot.model, color: bot.color, mascot: bot.mascot }); }, [bot.id]);
  const dirty = (Object.keys(form) as (keyof typeof form)[]).some((k) => form[k] !== (bot as any)[k]);
  const save = async () => { try { await api.update(bot.id, form); notify('Saved'); onChanged(); } catch (e: any) { notify(e.message, true); } };
  const fresh = async () => { try { await api.newConversation(bot.id); notify(`${bot.name} starts a new conversation. Its memory and files are kept.`); onChanged(); } catch (e: any) { notify(e.message, true); } };
  const remove = async () => { try { await api.remove(bot.id); onDeleted(); } catch (e: any) { notify(e.message, true); } };
  return (
    <div className="wrap">
      <div className="row">
        <div className="field"><label htmlFor="s-name">Name</label><input id="s-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></div>
        <div className="field"><label htmlFor="s-role">Role</label><input id="s-role" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })} placeholder="Researcher" /></div>
      </div>
      <div className="field"><label htmlFor="s-instr">Standing instructions</label>
        <textarea id="s-instr" value={form.instructions} onChange={(e) => setForm({ ...form, instructions: e.target.value })} placeholder="What this bot is for, and how you like things done." />
        <small>Changes apply from the next new conversation.</small></div>
      <ModelPicker provider={form.provider} model={form.model} onChange={(provider, model) => setForm({ ...form, provider, model })} />
      <div className="field"><span className="label">Mascot</span>
        <MascotPicker mascot={form.mascot} color={form.color} onChange={(mascot, color) => setForm({ ...form, mascot, color })} /></div>
      <div className="bar">
        <button className="btn primary tall" disabled={!dirty} onClick={save}>Save changes</button>
        <span style={{ flex: 1 }} />
        <button className="btn" onClick={() => setRecipe(true)}><Icon name="share" />Share recipe</button>
        <button className="btn" onClick={fresh}>New conversation</button>
        <button className="btn danger" onClick={() => setConfirm(true)}><Icon name="trash" />Delete bot</button>
      </div>
      {recipe ? <ShareRecipe bot={bot} notify={notify} onClose={() => setRecipe(false)} /> : null}
      {confirm ? (
        <Dialog title={`Delete ${bot.name}?`} intro="This removes the bot, its folder and files, its memory, its routines and its inbox. It can't be undone." onClose={() => setConfirm(false)}>
          <div className="foot"><button className="btn ghost" onClick={() => setConfirm(false)}>Keep it</button><button className="btn danger" onClick={remove}>Delete {bot.name}</button></div>
        </Dialog>
      ) : null}
    </div>
  );
}

const COLORS = ['#5ad1e6', '#f0892b', '#26b97a', '#8a5cf5', '#e5505b', '#e2b93b', '#4f8df7', '#d86ad0'];

export function MascotPicker({ mascot, color, onChange }: { mascot: string; color: string; onChange: (mascot: string, color: string) => void }) {
  return (
    <>
      <div className="mascots" role="group" aria-label="Mascot">
        {MASCOT_NAMES.map((m) => (
          <button key={m} type="button" className={m === mascot ? 'on' : ''} aria-pressed={m === mascot} aria-label={m} title={m} onClick={() => onChange(m, color)}>
            <Avatar bot={{ name: m, color, mascot: m }} size="md" />
          </button>
        ))}
      </div>
      <Swatches value={color} onChange={(c) => onChange(mascot, c)} />
    </>
  );
}

export function Swatches({ value, onChange }: { value: string; onChange: (c: string) => void }) {
  return <div className="swatches">{COLORS.map((c) => <button key={c} type="button" className={c === value ? 'on' : ''} style={{ background: c }} aria-label={`Colour ${c}`} aria-pressed={c === value} onClick={() => onChange(c)} />)}</div>;
}

export function ModelPicker({ provider, model, onChange }: { provider: string; model: string; onChange: (provider: string, model: string) => void }) {
  const [providers, setProviders] = useState<Provider[]>([]);
  const [models, setModels] = useState<{ id: string; label: string }[]>([]);
  useEffect(() => { api.providers().then((r) => setProviders(r.providers.filter((p) => p.configured && (p.kind || 'chat') === 'chat'))).catch(() => {}); }, []);
  useEffect(() => {
    let alive = true;
    setModels([]);
    api.models(provider).then((r) => { if (alive) setModels(r.models); }).catch(() => {});
    return () => { alive = false; };
  }, [provider]);
  useEffect(() => { if (models.length && !models.some((m) => m.id === model)) onChange(provider, models[0].id); }, [models]);  // eslint-disable-line react-hooks/exhaustive-deps
  const known = providers.some((p) => p.id === provider) ? providers : [{ id: provider, configured: true } as Provider, ...providers];
  return (
    <div className="row">
      <div className="field"><label htmlFor="m-provider">Model from</label>
        <select id="m-provider" value={provider} onChange={(e) => onChange(e.target.value, '')}>
          {known.map((p) => <option key={p.id} value={p.id}>{p.id === 'free' ? 'Mtrini free model' : p.label || p.name || p.id}</option>)}
        </select>
        <small>{provider === 'free' ? 'Free, no key. One request at a time and a daily allowance, so bots take turns.'
          : known.find((p) => p.id === provider)?.agentCli ? 'This program runs its own agent in the bot\'s folder, by its own permission settings. Mtrini\'s approvals and the bot\'s browser do not apply.'
          : 'More models: install OpenCode for its free ones, or set up a key in Mtrini Workspace (the two apps share them).'}</small></div>
      <div className="field"><label htmlFor="m-model">Model</label>
        <select id="m-model" value={model} onChange={(e) => onChange(provider, e.target.value)} disabled={models.length === 0}>
          {models.length === 0 ? <option value={model}>{model || 'Default'}</option> : models.map((m) => <option key={m.id} value={m.id}>{m.label || m.id}</option>)}
        </select></div>
    </div>
  );
}
