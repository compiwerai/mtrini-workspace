import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import ArenaView from './components/ArenaView';
import TopBar from './components/TopBar';

function sseBody(events: any[]) {
  const text = events.map((e) => `data: ${JSON.stringify(e)}\n\n`).join('');
  return new Response(text, { headers: { 'content-type': 'text/event-stream' } });
}

afterEach(() => { vi.unstubAllGlobals(); localStorage.clear(); });

describe('arena', () => {
  it('runs one prompt on two models side by side and keeps a leaderboard', async () => {
    const asked: any[] = [];
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: any) => {
      const u = new URL(url, 'http://x');
      if (u.pathname === '/api/providers') {
        return new Response(JSON.stringify({ providers: [
          { id: 'free', label: 'Free', configured: true, kind: 'chat', defaultModel: 'qwen' },
          { id: 'openai', label: 'OpenAI', configured: true, kind: 'chat', defaultModel: 'gpt-x' },
          { id: 'claude-code', label: 'Claude Code', configured: true, kind: 'chat', agentCli: true },
        ] }));
      }
      if (u.pathname === '/api/models') return new Response(JSON.stringify({ models: [] }));
      if (u.pathname === '/api/chat') {
        const b = JSON.parse(init.body);
        asked.push(b);
        return sseBody([{ delta: `answer from ${b.model}` }, { done: true }]);
      }
      return new Response('{}');
    }));
    render(<ArenaView onUse={() => {}} />);
    await waitFor(() => expect(screen.getByLabelText('Provider B')).toBeTruthy());
    // CLI agents can't answer one-off prompts, so they aren't offered.
    expect(screen.queryByRole('option', { name: 'Claude Code' })).toBeNull();
    fireEvent.change(screen.getByPlaceholderText(/merges overlapping/), { target: { value: 'hi' } });
    fireEvent.click(screen.getByRole('button', { name: 'Compare' }));
    await waitFor(() => expect(screen.getByText('answer from gpt-x')).toBeTruthy());
    expect(screen.getByText('answer from qwen')).toBeTruthy();
    expect(asked.map((a) => a.provider).sort()).toEqual(['free', 'openai']);

    fireEvent.click(screen.getAllByRole('button', { name: /Better/ })[1]);
    expect(JSON.parse(localStorage.getItem('mtrini.arena.board') || '{}')).toEqual({
      'free:qwen': { wins: 0, games: 1 }, 'openai:gpt-x': { wins: 1, games: 1 } });
    expect(screen.getByText('Your leaderboard')).toBeTruthy();
  });
});

describe('export menu', () => {
  it('offers HTML and Markdown only when a session is open', () => {
    const onExport = vi.fn();
    const { rerender } = render(<TopBar title="t" project="" onOpen={() => {}} onCommit={() => {}} diffOpen={false} onToggleDiff={() => {}} />);
    expect(screen.queryByRole('button', { name: /Export/ })).toBeNull();
    rerender(<TopBar title="t" project="" onOpen={() => {}} onCommit={() => {}} diffOpen={false} onToggleDiff={() => {}} onExport={onExport} />);
    fireEvent.click(screen.getByRole('button', { name: /Export/ }));
    fireEvent.click(screen.getByRole('menuitem', { name: /Markdown/ }));
    expect(onExport).toHaveBeenCalledWith('md');
  });
});

describe('swarm', () => {
  it('splits a goal into parts, starts agents, shows them and merges one', async () => {
    const SwarmView = (await import('./components/SwarmView')).default;
    const calls: { path: string; body?: any }[] = [];
    const worker = (n: number, status: string) => ({
      n, task: `part ${n + 1}`, provider: 'free', model: 'qwen', branch: `mtrini/swarm-ab-${n + 1}`, status,
      summary: status === 'done' ? 'Added it and ran the tests' : '', error: '', stat: '1 file changed', files: status === 'failed' ? [] : [`f${n}.txt`],
      steps: 2, started: 1, ended: 2, events: [{ kind: 'tool', tool: 'write_file', target: `f${n}.txt`, ok: true }] });
    let swarms: any[] = [];
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: any) => {
      const u = new URL(url, 'http://x');
      const body = init?.body ? JSON.parse(init.body) : undefined;
      calls.push({ path: `${init?.method || 'GET'} ${u.pathname}`, body });
      if (u.pathname === '/api/providers') return new Response(JSON.stringify({ providers: [
        { id: 'free', label: 'Free', configured: true, kind: 'chat', defaultModel: 'qwen' },
        { id: 'claude-code', label: 'Claude Code (your subscription)', configured: true, kind: 'chat', agentCli: true }] }));
      if (u.pathname === '/api/models') return new Response(JSON.stringify({ models: [{ id: 'qwen', label: 'Qwen' }] }));
      if (u.pathname === '/api/swarm/plan') return new Response(JSON.stringify({ tasks: ['Build the API', 'Build the UI'] }));
      if (u.pathname === '/api/swarm' && init?.method === 'POST') {
        swarms = [{ id: 'ab', goal: body.goal, mode: 'split', permission: 'auto', base_branch: 'main', created: 1, running: false,
          workers: [worker(0, 'done'), worker(1, 'failed')] }];
        return new Response(JSON.stringify(swarms[0]));
      }
      if (u.pathname === '/api/swarm') return new Response(JSON.stringify({ swarms, maxAgents: 4 }));
      if (u.pathname === '/api/swarm/ab/merge/0') { swarms[0].workers[0].status = 'merged'; return new Response('{"ok":true}'); }
      return new Response('{}');
    }));
    render(<SwarmView />);
    // Your own CLI agents can be swarm agents too.
    await waitFor(() => expect(screen.getAllByRole('option', { name: 'Claude Code (your subscription)' }).length).toBeGreaterThan(0));
    fireEvent.change(screen.getByLabelText('Swarm goal'), { target: { value: 'Add search' } });
    fireEvent.click(screen.getByRole('button', { name: /Split into parts/ }));
    await waitFor(() => expect((screen.getByLabelText('Task for agent 2') as HTMLTextAreaElement).value).toBe('Build the UI'));
    fireEvent.click(screen.getByRole('button', { name: 'Start 2 agents' }));
    await waitFor(() => expect(screen.getByText('Ready to merge')).toBeTruthy());
    const start = calls.find((c) => c.path === 'POST /api/swarm')!;
    expect(start.body.agents.map((a: any) => a.task)).toEqual(['Build the API', 'Build the UI']);
    expect(start.body.permission).toBe('auto');
    expect(screen.getByText('Failed')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Merge into main' }));
    await waitFor(() => expect(screen.getByText('Merged')).toBeTruthy());
  });
});
