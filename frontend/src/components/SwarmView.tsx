import React, { useCallback, useEffect, useState } from 'react';
import { api } from '../api/client';
import { I } from './Icon';

type Agent = { task: string; provider: string; model: string };
type Ev = { kind: 'tool' | 'text' | 'status'; tool?: string; target?: string; ok?: boolean; text?: string };
type Worker = {
  n: number; task: string; provider: string; model: string; branch: string; status: string;
  summary: string; error: string; stat: string; files: string[]; steps: number; started: number; ended: number; events: Ev[];
};
type Swarm = { id: string; goal: string; mode: 'split' | 'best'; permission: string; base_branch: string; created: number; running: boolean; workers: Worker[] };

/** Pull the readable message out of an API error ("409 {"detail": "…"}"). */
export function errText(e: any): string {
  const s = String(e?.message || e);
  const m = /^\d{3} (.*)$/s.exec(s);
  if (m) { try { return JSON.parse(m[1]).detail || m[1]; } catch { return m[1]; } }
  return s;
}

const STATUS: Record<string, string> = {
  queued: 'Waiting', running: 'Working', done: 'Ready to merge', failed: 'Failed', blocked: 'Blocked',
  stopped: 'Stopped', merged: 'Merged', discarded: 'Discarded',
};

function since(t: number, end?: number) {
  if (!t) return '';
  const s = Math.max(0, Math.round(((end || Date.now() / 1000) - t)));
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`;
}

function AgentRow({ a, i, providers, mode, onChange, onRemove }: {
  a: Agent; i: number; providers: any[]; mode: 'split' | 'best';
  onChange: (a: Agent) => void; onRemove?: () => void;
}) {
  const [models, setModels] = useState<any[]>([]);
  useEffect(() => {
    if (!a.provider) return;
    api.models(a.provider).then((r) => {
      const ms = r.models || [];
      setModels(ms);
      if (!a.model && ms[0]) onChange({ ...a, model: ms[0].id });
    }).catch(() => setModels([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [a.provider]);
  return (
    <div className="swarm-agent">
      <span className="swarm-n" aria-hidden="true">{i + 1}</span>
      <div className="swarm-agent-main">
        {mode === 'split' && (
          <textarea className="t" rows={2} aria-label={`Task for agent ${i + 1}`} value={a.task}
            onChange={(e) => onChange({ ...a, task: e.target.value })} placeholder="What this agent should do" />
        )}
        <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
          <select className="pillselect" aria-label={`Provider for agent ${i + 1}`} value={a.provider}
            onChange={(e) => onChange({ ...a, provider: e.target.value, model: '' })}>
            {providers.map((p) => <option key={p.id} value={p.id}>{p.label || p.id}</option>)}
          </select>
          <input className="pillselect" aria-label={`Model for agent ${i + 1}`} list={`swarm-models-${i}`} value={a.model}
            onChange={(e) => onChange({ ...a, model: e.target.value.trim() })} placeholder="model id" />
          <datalist id={`swarm-models-${i}`}>{models.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}</datalist>
          {onRemove && <button className="btn" onClick={onRemove} aria-label={`Remove agent ${i + 1}`}>{I.x()}</button>}
        </div>
      </div>
    </div>
  );
}

function DiffView({ text }: { text: string }) {
  return (
    <pre className="swarm-diff">
      {text.split('\n').map((l, i) => (
        <span key={i} className={l.startsWith('+') && !l.startsWith('+++') ? 'add' : l.startsWith('-') && !l.startsWith('---') ? 'del' : l.startsWith('@@') ? 'hunk' : ''}>{l}{'\n'}</span>
      ))}
    </pre>
  );
}

function WorkerCard({ sw, w, onAction, busy }: { sw: Swarm; w: Worker; onAction: (a: 'merge' | 'discard' | 'diff', n: number) => void; busy: boolean }) {
  const live = w.status === 'running' || w.status === 'queued';
  const tools = w.events.filter((e) => e.kind === 'tool').slice(-6);
  return (
    <section className={`swarm-worker s-${w.status}`} aria-label={`Agent ${w.n + 1}`}>
      <header>
        <span className={`swarm-dot s-${w.status}`} aria-hidden="true" />
        <strong>Agent {w.n + 1}</strong>
        <span className="muted">{STATUS[w.status] || w.status}{live && w.started ? ` · ${since(w.started)}` : ''}</span>
      </header>
      <div className="mono muted swarm-model">{w.provider}{w.model ? ` · ${w.model}` : ''}</div>
      {sw.mode === 'split' && <p className="swarm-task">{w.task}</p>}
      {tools.length > 0 && (
        <ul className="swarm-steps" aria-label="Recent steps">
          {tools.map((e, i) => (
            <li key={i} className={e.ok === false ? 'bad' : ''}><span className="mono">{e.tool}</span> {e.target}</li>
          ))}
        </ul>
      )}
      {w.summary && <p className="swarm-summary">{w.summary.slice(-400)}</p>}
      {w.error && <p className="err">{w.error}</p>}
      <footer className="row">
        <span className="mono muted">{w.steps} steps{w.stat ? ` · ${w.stat}` : ''}</span>
        <span style={{ flex: 1 }} />
        {w.files.length > 0 && !['merged', 'discarded'].includes(w.status) && (
          <button className="btn" onClick={() => onAction('diff', w.n)}>Changes</button>
        )}
        {['done', 'blocked', 'stopped', 'failed'].includes(w.status) && w.files.length > 0 && (
          <button className="btn primary" disabled={busy} onClick={() => onAction('merge', w.n)}>Merge into {sw.base_branch}</button>
        )}
        {!['merged', 'discarded'].includes(w.status) && (
          <button className="btn" disabled={busy} onClick={() => onAction('discard', w.n)}>{live ? 'Stop and discard' : 'Discard'}</button>
        )}
      </footer>
    </section>
  );
}

/** Agent Swarm: several agents at once, each in its own git worktree; merge the results you want. */
export default function SwarmView() {
  const [providers, setProviders] = useState<any[]>([]);
  const [goal, setGoal] = useState('');
  const [mode, setMode] = useState<'split' | 'best'>('split');
  const [permission, setPermission] = useState<'auto' | 'readonly'>('auto');
  const [agents, setAgents] = useState<Agent[]>([]);
  const [planning, setPlanning] = useState(false);
  const [starting, setStarting] = useState(false);
  const [swarms, setSwarms] = useState<Swarm[]>([]);
  const [max, setMax] = useState(4);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const [diff, setDiff] = useState<{ title: string; text: string } | null>(null);

  const load = useCallback(() => api.swarms().then((r) => { setSwarms(r.swarms || []); setMax(r.maxAgents || 4); }).catch(() => {}), []);
  useEffect(() => {
    load();
    api.providers().then((r) => {
      const ps = (r.providers || []).filter((p: any) => p.configured && p.kind !== 'image');
      setProviders(ps);
      const first = ps[0];
      if (first) setAgents([0, 1].map(() => ({ task: '', provider: first.id, model: first.defaultModel || '' })));
    }).catch(() => {});
  }, [load]);
  const running = swarms.some((s) => s.running);
  useEffect(() => {
    if (!running) return;
    const t = setInterval(load, 1500);
    return () => clearInterval(t);
  }, [running, load]);

  const planner = providers.find((p) => !p.agentCli && p.id === agents[0]?.provider) ? agents[0]
    : (() => { const p = providers.find((x) => !x.agentCli); return p ? { provider: p.id, model: p.defaultModel || '' } : null; })();

  const plan = async () => {
    if (!goal.trim() || !planner) return;
    setPlanning(true); setErr('');
    try {
      const r = await api.swarmPlan(goal, planner.provider, planner.model, agents.length || 3);
      const base = agents[0] || { provider: planner.provider, model: planner.model, task: '' };
      setAgents(r.tasks.map((task, i) => ({ ...(agents[i] || base), task })));
    } catch (e) { setErr(errText(e)); }
    finally { setPlanning(false); }
  };

  const start = async () => {
    setStarting(true); setErr('');
    try {
      const list = agents.map((a) => ({ ...a, task: mode === 'best' ? goal : a.task }));
      await api.swarmStart({ goal, mode, permission, agents: list });
      setGoal('');
      setAgents((cur) => cur.map((a) => ({ ...a, task: '' })));
      await load();
    } catch (e) { setErr(errText(e)); }
    finally { setStarting(false); }
  };

  const act = async (sw: Swarm, a: 'merge' | 'discard' | 'diff', n: number) => {
    setErr('');
    if (a === 'diff') {
      try { setDiff({ title: `Agent ${n + 1}: ${sw.workers[n].branch}`, text: (await api.swarmDiff(sw.id, n)).diff || 'No changes' }); }
      catch (e) { setErr(errText(e)); }
      return;
    }
    setBusy(true);
    try {
      if (a === 'merge') await api.swarmMerge(sw.id, n);
      else await api.swarmDiscard(sw.id, n);
      window.dispatchEvent(new CustomEvent('mtrini:toast', { detail: a === 'merge' ? `Merged agent ${n + 1} into ${sw.base_branch}` : `Discarded agent ${n + 1}` }));
      await load();
    } catch (e) { setErr(errText(e)); }
    finally { setBusy(false); }
  };

  const ready = goal.trim() && agents.length > 0 && agents.every((a) => a.provider && (mode === 'best' || a.task.trim())) && !starting;

  return (
    <div className="view swarm">
      <h2>Swarm</h2>
      <p style={{ color: 'var(--muted)' }}>
        Run several agents at once. Each one works in its own copy of your repository on its own branch, so they never get in each
        other's way and your folder stays as it is. When they finish, merge the results you want.
      </p>

      {providers.length === 0 ? (
        <div className="card"><p className="hint">Connect a provider in Settings → Providers first. The free model counts, and so do Claude Code, Codex and Gemini CLI.</p></div>
      ) : (
        <div className="card">
          <div className="seg" role="radiogroup" aria-label="Swarm mode">
            <button role="radio" aria-checked={mode === 'split'} className={mode === 'split' ? 'on' : ''} onClick={() => setMode('split')}>
              Split the work<small>One goal, a different part for each agent</small></button>
            <button role="radio" aria-checked={mode === 'best'} className={mode === 'best' ? 'on' : ''} onClick={() => setMode('best')}>
              Best of {agents.length || 'N'}<small>The same task for every agent; keep the best</small></button>
          </div>
          <label className="f">Goal</label>
          <textarea className="t" rows={3} value={goal} onChange={(e) => setGoal(e.target.value)} aria-label="Swarm goal"
            placeholder={mode === 'split' ? 'Add a product search page: API endpoint, UI with filters, and tests' : 'Fix the flaky checkout test and explain the cause'} />
          {mode === 'split' && (
            <div className="row" style={{ marginTop: 8 }}>
              <button className="btn" onClick={plan} disabled={!goal.trim() || planning || !planner}
                title={planner ? `Planned by ${planner.provider}${planner.model ? ` · ${planner.model}` : ''}` : 'Needs a chat model'}>
                {I.wand()} {planning ? 'Planning…' : 'Split into parts'}</button>
              <span className="hint" style={{ margin: 0 }}>Or write each agent's part yourself.</span>
            </div>
          )}
          <div className="label-caps" style={{ marginTop: 14 }}>Agents</div>
          {agents.map((a, i) => (
            <AgentRow key={i} a={a} i={i} providers={providers} mode={mode}
              onChange={(v) => setAgents((cur) => cur.map((x, j) => (j === i ? v : x)))}
              onRemove={agents.length > 1 ? () => setAgents((cur) => cur.filter((_, j) => j !== i)) : undefined} />
          ))}
          <div className="row" style={{ marginTop: 8, flexWrap: 'wrap', gap: 8 }}>
            {agents.length < max && (
              <button className="btn" onClick={() => setAgents((cur) => [...cur, { ...(cur[cur.length - 1] || { provider: providers[0].id, model: '' }), task: '' }])}>
                {I.plus()} Add an agent</button>
            )}
            <span style={{ flex: 1 }} />
            <select className="pillselect" aria-label="What agents may do" value={permission} onChange={(e) => setPermission(e.target.value as 'auto' | 'readonly')}
              title="Swarm agents can't stop to ask you, so pick what they may do up front">
              <option value="auto">Edit and run commands in their copy</option>
              <option value="readonly">Read only (research)</option>
            </select>
            <button className="btn primary" onClick={start} disabled={!ready}>{starting ? 'Starting…' : `Start ${agents.length} agent${agents.length === 1 ? '' : 's'}`}</button>
          </div>
          {permission === 'auto' && (
            <p className="hint">Agents run commands on this computer without asking, inside their own copy of the repo. Anything they do outside it, like installing packages globally, isn't isolated.</p>
          )}
        </div>
      )}
      {err && <p className="err" role="alert">{err}</p>}

      {swarms.map((sw) => (
        <div key={sw.id} className="card swarm-run">
          <div className="row" style={{ alignItems: 'flex-start' }}>
            <div style={{ flex: 1, minWidth: 0 }}>
              <strong className="swarm-goal">{sw.goal}</strong>
              <div className="muted">{sw.mode === 'split' ? 'Split' : 'Best of N'} · from {sw.base_branch} · {new Date(sw.created * 1000).toLocaleString()}
                {sw.permission === 'readonly' ? ' · read only' : ''}</div>
            </div>
            {sw.running && <button className="btn" onClick={() => api.swarmStop(sw.id).then(load)}>{I.stop()} Stop all</button>}
            {!sw.running && (
              <button className="btn" onClick={() => { if (confirm('Remove this swarm? Branches that were not merged are deleted.')) api.swarmDelete(sw.id).then(load).catch((e) => setErr(errText(e))); }}
                aria-label="Remove swarm">{I.trash()}</button>
            )}
          </div>
          <div className={`swarm-grid cols-${Math.min(sw.workers.length, 4)}`}>
            {sw.workers.map((w) => <WorkerCard key={w.n} sw={sw} w={w} busy={busy} onAction={(a, n) => act(sw, a, n)} />)}
          </div>
        </div>
      ))}

      {diff && (
        <div className="modal" onClick={() => setDiff(null)} role="dialog" aria-label="Agent changes">
          <div className="sheet wide" onClick={(e) => e.stopPropagation()}>
            <div className="row"><strong className="mono">{diff.title}</strong><span style={{ flex: 1 }} />
              <button className="btn" onClick={() => setDiff(null)} aria-label="Close">{I.x()}</button></div>
            <DiffView text={diff.text} />
          </div>
        </div>
      )}
    </div>
  );
}
