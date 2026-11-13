import React, { useEffect, useRef, useState } from 'react';
import { api, sse } from '../api/client';
import { Body as Markdown } from './ThreadView';
import { I } from './Icon';

type Slot = { provider: string; model: string };
type Result = { text: string; error?: string; firstMs?: number; totalMs?: number; running: boolean };
type Board = Record<string, { wins: number; games: number }>;

const BOARD_KEY = 'mtrini.arena.board';
const SLOTS_KEY = 'mtrini.arena.slots';

function load<T>(key: string, fallback: T): T {
  try { return JSON.parse(localStorage.getItem(key) || '') ?? fallback; } catch { return fallback; }
}
function store(key: string, v: unknown) {
  try { localStorage.setItem(key, JSON.stringify(v)); } catch { /* private mode */ }
}
const label = (s: Slot) => `${s.provider}:${s.model}`;

function SlotPicker({ slot, providers, onChange, onRemove, hidden, n }: {
  slot: Slot; providers: any[]; onChange: (s: Slot) => void; onRemove?: () => void; hidden: boolean; n: number;
}) {
  const [models, setModels] = useState<any[]>([]);
  useEffect(() => {
    if (!slot.provider) return;
    api.models(slot.provider).then((r) => {
      const ms = r.models || [];
      setModels(ms);
      if (!slot.model && ms[0]) onChange({ ...slot, model: ms[0].id });
    }).catch(() => setModels([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slot.provider]);
  return (
    <div className="arena-pick">
      <span className="arena-n">{hidden ? `Model ${'ABC'[n]}` : `${'ABC'[n]}`}</span>
      <select className="pillselect" aria-label={`Provider ${'ABC'[n]}`} value={slot.provider}
        onChange={(e) => onChange({ provider: e.target.value, model: '' })}>
        {providers.map((p) => <option key={p.id} value={p.id}>{p.label || p.id}</option>)}
      </select>
      <input className="pillselect" aria-label={`Model ${'ABC'[n]}`} list={`arena-models-${n}`} value={slot.model}
        onChange={(e) => onChange({ ...slot, model: e.target.value.trim() })} placeholder="model id" />
      <datalist id={`arena-models-${n}`}>{models.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}</datalist>
      {onRemove && <button className="btn" onClick={onRemove} aria-label={`Remove model ${'ABC'[n]}`}>{I.x()}</button>}
    </div>
  );
}

/** Mtrini Arena: one prompt, two or three models side by side, timed, optionally blind. */
export default function ArenaView({ onUse }: { onUse: (text: string) => void }) {
  const [providers, setProviders] = useState<any[]>([]);
  const [slots, setSlots] = useState<Slot[]>(() => load<Slot[]>(SLOTS_KEY, []));
  const [prompt, setPrompt] = useState('');
  const [results, setResults] = useState<Result[]>([]);
  const [blind, setBlind] = useState(false);
  const [voted, setVoted] = useState<number | null>(null);
  const [board, setBoard] = useState<Board>(() => load<Board>(BOARD_KEY, {}));
  const ctrl = useRef<AbortController | null>(null);
  const ran = useRef<Slot[]>([]);

  useEffect(() => {
    api.providers().then((r) => {
      const ps = (r.providers || []).filter((p: any) => p.configured && p.kind !== 'image' && !p.agentCli);
      setProviders(ps);
      setSlots((cur) => {
        const ok = cur.filter((s) => ps.some((p: any) => p.id === s.provider));
        if (ok.length >= 2) return ok.slice(0, 3);
        const fill = ps.slice(0, 2).map((p: any) => ({ provider: p.id, model: p.defaultModel || '' }));
        return [...ok, ...fill].slice(0, Math.max(2, ok.length));
      });
    }).catch(() => setProviders([]));
    return () => ctrl.current?.abort();
  }, []);
  useEffect(() => { store(SLOTS_KEY, slots); }, [slots]);

  const running = results.some((r) => r.running);
  const ready = slots.length >= 2 && slots.every((s) => s.provider && s.model) && prompt.trim() && !running;

  const run = async () => {
    if (!ready) return;
    ctrl.current?.abort();
    const c = new AbortController();
    ctrl.current = c;
    ran.current = slots.map((s) => ({ ...s }));
    setVoted(null);
    setResults(slots.map(() => ({ text: '', running: true })));
    const patch = (i: number, p: Partial<Result>) => setResults((rs) => rs.map((r, j) => (j === i ? { ...r, ...p } : r)));
    await Promise.all(ran.current.map(async (s, i) => {
      const t0 = performance.now();
      let text = '';
      try {
        for await (const ev of sse<any>('/api/chat', { provider: s.provider, model: s.model, messages: [{ role: 'user', content: prompt }] }, c.signal)) {
          if (ev.error) { patch(i, { error: ev.error }); break; }
          if (ev.delta) {
            if (!text) patch(i, { firstMs: Math.round(performance.now() - t0) });
            text += ev.delta;
            patch(i, { text });
          }
        }
      } catch (e: any) {
        if (e?.name !== 'AbortError') patch(i, { error: String(e?.message || e) });
      }
      patch(i, { running: false, totalMs: Math.round(performance.now() - t0) });
    }));
  };

  const vote = (i: number | 'tie') => {
    if (voted !== null || running || !results.length) return;
    setVoted(i === 'tie' ? -1 : i);
    // The same model twice says nothing about which model is better: don't count it.
    if (new Set(ran.current.map(label)).size < ran.current.length) return;
    const next = { ...board };
    ran.current.forEach((s, j) => {
      const k = label(s);
      const e = next[k] || { wins: 0, games: 0 };
      next[k] = { wins: e.wins + (i === j ? 1 : 0), games: e.games + 1 };
    });
    setBoard(next);
    store(BOARD_KEY, next);
  };

  const ranked = Object.entries(board).sort((a, b) => (b[1].wins / b[1].games) - (a[1].wins / a[1].games) || b[1].games - a[1].games);
  const reveal = !blind || voted !== null;

  return (
    <div className="view arena">
      <h2>Arena</h2>
      <p style={{ color: 'var(--muted)' }}>Send one prompt to two or three models at once and compare the answers. Votes stay on this computer.</p>

      {providers.length === 0 ? (
        <div className="card"><p className="hint">Connect at least one chat provider in Settings → Providers first. The free model counts.</p></div>
      ) : (
        <div className="card">
          <div className="arena-slots">
            {slots.map((s, i) => (
              <SlotPicker key={i} n={i} slot={s} providers={providers} hidden={blind}
                onChange={(v) => setSlots((cur) => cur.map((x, j) => (j === i ? v : x)))}
                onRemove={slots.length > 2 ? () => setSlots((cur) => cur.filter((_, j) => j !== i)) : undefined} />
            ))}
            {slots.length < 3 && (
              <button className="btn" onClick={() => setSlots((cur) => [...cur, { provider: providers[0].id, model: '' }])}>{I.plus()} Add a model</button>
            )}
          </div>
          <label className="f">Prompt</label>
          <textarea className="t" rows={3} value={prompt} onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={(e) => { if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') run(); }}
            placeholder="Write a Python function that merges overlapping intervals, with tests" />
          <div className="row" style={{ marginTop: 8 }}>
            <button className="btn primary" onClick={run} disabled={!ready}>{running ? 'Running…' : 'Compare'}</button>
            {running && <button className="btn" onClick={() => ctrl.current?.abort()}>{I.stop()} Stop</button>}
            <label className="row" style={{ gap: 6, marginLeft: 8 }}>
              <input type="checkbox" aria-label="Blind: hide names until I vote" checked={blind} onChange={(e) => setBlind(e.target.checked)} /> Blind: hide names until I vote
            </label>
          </div>
        </div>
      )}

      {results.length > 0 && (
        <>
          <div className={`arena-grid cols-${results.length}`}>
            {results.map((r, i) => (
              <section key={i} className={`arena-col ${voted === i ? 'won' : ''}`} aria-label={`Answer ${'ABC'[i]}`}>
                <header>
                  <strong>{reveal ? label(ran.current[i]) : `Model ${'ABC'[i]}`}</strong>
                  <span className="mono muted">
                    {r.firstMs !== undefined ? `first token ${(r.firstMs / 1000).toFixed(1)}s` : r.running ? 'waiting…' : ''}
                    {r.totalMs !== undefined && !r.running ? ` · ${(r.totalMs / 1000).toFixed(1)}s · ${r.text.length.toLocaleString()} chars` : ''}
                  </span>
                </header>
                <div className="arena-body">
                  {r.error ? <p className="err">{r.error}</p> : r.text ? <Markdown text={r.text} /> : <p className="muted">{r.running ? '…' : 'No answer'}</p>}
                </div>
                <footer className="row">
                  <button className="btn" disabled={running || voted !== null} onClick={() => vote(i)}>{voted === i && I.check()} Better</button>
                  <button className="btn" disabled={!r.text} onClick={() => onUse(r.text)}>Use in a session</button>
                </footer>
              </section>
            ))}
          </div>
          {!running && voted === null && (
            <div className="row" style={{ justifyContent: 'center', marginTop: 8 }}>
              <button className="btn" onClick={() => vote('tie')}>It's a tie</button>
            </div>
          )}
        </>
      )}

      {ranked.length > 0 && (
        <div className="card" style={{ marginTop: 16 }}>
          <div className="row"><strong>Your leaderboard</strong><span className="grow" style={{ flex: 1 }} />
            <button className="btn" onClick={() => { setBoard({}); store(BOARD_KEY, {}); }}>Reset</button></div>
          <table className="arena-board">
            <thead><tr><th>Model</th><th>Win rate</th><th>Wins</th><th>Rounds</th></tr></thead>
            <tbody>
              {ranked.map(([k, v]) => (
                <tr key={k}><td className="mono">{k}</td>
                  <td><span className="bar"><span style={{ width: `${Math.round((100 * v.wins) / v.games)}%` }} /></span>{Math.round((100 * v.wins) / v.games)}%</td>
                  <td className="num">{v.wins}</td><td className="num">{v.games}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
