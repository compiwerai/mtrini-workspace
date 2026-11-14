import React from 'react';
import { act, cleanup, configure, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import BotsApp from './BotsApp';
import { toHtml } from './parts';

configure({ asyncUtilTimeout: 5000 });  // a slow machine running the whole suite needs more than the default second

const bot = (over: Record<string, unknown> = {}) => ({
  id: 'scout', name: 'Scout', role: 'Researcher', instructions: '', provider: 'free', model: 'm', effort: 'off', color: '#5ad1e6', mascot: 'fennec',
  created: 1, paused: false, session: 1, state: { status: 'idle', label: '', since: 0 }, busy: false, folder: 'C:/bots/scout/files',
  routines: 1, unread: 0, waiting: 0, ...over,
});

type Call = { url: string; method: string; body: any };
let calls: Call[] = [];
let state: { bots: any[]; inbox: any[]; conversation: any[] };

function mockApi() {
  calls = [];
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo, init?: RequestInit) => {
    const url = String(input);
    const method = (init?.method || 'GET').toUpperCase();
    const body = init?.body ? JSON.parse(String(init.body)) : null;
    calls.push({ url, method, body });
    const ok = (data: unknown) => ({ ok: true, status: 200, json: async () => data }) as Response;
    if (url === '/api/bots' && method === 'GET') return ok({ bots: state.bots, unread: 0, browser: true, colors: [] });
    if (url === '/api/bots' && method === 'POST') { const b = bot({ id: 'atlas', name: body.name }); state.bots.push(b); return ok(b); }
    if (url === '/api/bots/inbox') return ok({ items: state.inbox, unread: state.inbox.filter((i) => !i.read).length });
    if (url === '/api/bots/background' && method === 'GET') return ok({ keepRunning: false, autostart: false, installed: false, desktop: false, hasWork: true, staysOn: false });
    if (url === '/api/bots/background' && method === 'POST') return ok({ keepRunning: !!body.keepRunning, autostart: false, installed: false, desktop: false, hasWork: true, staysOn: !!body.keepRunning });
    if (url === '/api/bots/telegram') return ok({ connected: false, paired: false, pairCode: '', defaultBot: '', username: '', running: false, error: '' });
    if (url === '/api/bots/templates') return ok({ templates: [
      { key: 'chief', name: 'Atlas', role: 'Chief of staff', instructions: 'Keep me on top of my day.', mascot: 'camel', routines: ['Morning briefing'] },
      { key: 'blank', name: '', role: '', instructions: '', mascot: '', routines: [] }] });
    if (url === '/api/providers') return ok({ providers: [{ id: 'free', configured: true, kind: 'chat', free: true }] });
    if (url.startsWith('/api/models')) return ok({ models: [{ id: 'm', label: 'Mtrini Free' }] });
    if (url.endsWith('/conversation')) return ok({ messages: state.conversation, state: { status: 'idle', label: '', since: 0 }, busy: false });
    if (url.endsWith('/message')) return ok({ ok: true });
    if (url.endsWith('/resolve')) { state.inbox = state.inbox.map((i) => (i.kind === 'approval' ? { ...i, state: 'approved', read: true } : i)); return ok({}); }
    if (url.endsWith('/routines')) return ok({ routines: [{ id: 'r1', title: 'What\'s new', prompt: 'x', kind: 'daily', time: '09:00', enabled: true, when: 'Every day at 09:00', nextRun: Date.now() / 1000 + 7200 }] });
    return ok({});
  }));
}

beforeEach(() => { state = { bots: [], inbox: [], conversation: [] }; mockApi(); });
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe('Mtrini Bots', () => {
  it('invites you to make a first bot, then creates one from a template', async () => {
    render(<BotsApp />);
    expect(await screen.findByText('Bots that keep working, and ask before they act')).toBeTruthy();
    fireEvent.click(screen.getAllByRole('button', { name: 'New bot' })[0]);
    const name = await screen.findByLabelText('Name') as HTMLInputElement;
    await waitFor(() => expect(name.value).toBe('Atlas'));
    expect(screen.getByText('Comes with a routine: Morning briefing')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Create bot' }));
    await waitFor(() => expect(calls.some((c) => c.url === '/api/bots' && c.method === 'POST')).toBe(true));
    const made = calls.find((c) => c.url === '/api/bots' && c.method === 'POST')!;
    expect(made.body).toMatchObject({ name: 'Atlas', role: 'Chief of staff', template: 'chief', provider: 'free', mascot: 'camel' });
    expect(await screen.findByText(/Atlas keeps its notes in its own folder/)).toBeTruthy();
  });

  it('puts approvals first in the inbox and sends your answer', async () => {
    state.bots = [bot({ waiting: 1 })];
    state.inbox = [
      { id: 'b1', bot: 'scout', botName: 'Scout', botColor: '#5ad1e6', kind: 'briefing', title: 'What\'s new', body: 'Two releases:\n- A\n- B', ts: 10, read: false },
      { id: 'a1', bot: 'scout', botName: 'Scout', botColor: '#5ad1e6', kind: 'approval', title: 'Scout wants to: send the form', body: 'In its browser, on element [3].', ts: 5, read: false, state: 'pending' },
    ];
    render(<BotsApp />);
    expect(await screen.findByText('Needs you')).toBeTruthy();
    const titles = [...document.querySelectorAll('.mailrow .t b')].map((b) => b.textContent);
    expect(titles).toEqual(['Scout wants to: send the form', 'What\'s new']);
    expect(screen.getByLabelText('2 unread')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /Scout wants to: send the form/ }));
    expect(screen.getByText(/Nothing has been done yet/)).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }));
    await waitFor(() => expect(calls.find((c) => c.url === '/api/bots/inbox/scout/a1/resolve')?.body).toEqual({ decision: 'allow' }));
    expect(await screen.findByText('approved')).toBeTruthy();
  });

  it('shows a bot\'s conversation with its steps and sends a message', async () => {
    state.bots = [bot()];
    state.conversation = [
      { id: 'm1', role: 'user', content: 'What is new?', ts: 1 },
      { id: 'm2', role: 'assistant', content: 'Here is **one** thing: https://example.com', ts: 2, steps: [{ tool: 'web_search', label: 'Searched the web: news', ok: true }] },
    ];
    render(<BotsApp />);
    fireEvent.click(await screen.findByRole('button', { name: /Scout/ }));
    expect(await screen.findByText('What is new?')).toBeTruthy();
    expect(screen.getByText('1 step')).toBeTruthy();
    expect(screen.getByText('Searched the web: news')).toBeTruthy();
    expect(screen.getByRole('link', { name: 'https://example.com' })).toBeTruthy();
    const box = screen.getByLabelText('Message Scout');
    fireEvent.change(box, { target: { value: 'Thanks' } });
    fireEvent.keyDown(box, { key: 'Enter' });
    await waitFor(() => expect(calls.find((c) => c.url === '/api/bots/scout/message')?.body).toEqual({ text: 'Thanks' }));
    fireEvent.click(screen.getByRole('tab', { name: 'Routines' }));
    expect(await screen.findByText(/Every day at 09:00/)).toBeTruthy();
  });

  it('shows a reply even when another live update arrives in the same moment', async () => {
    let stream: { onmessage: ((m: { data: string }) => void) | null } | null = null;
    vi.stubGlobal('EventSource', class { onmessage = null; onerror = null; constructor() { stream = this as any; } close() {} });
    state.bots = [bot()];
    render(<BotsApp />);
    fireEvent.click(await screen.findByRole('button', { name: /Scout/ }));
    await screen.findByLabelText('Message Scout');
    const emit = (ev: unknown) => stream!.onmessage!({ data: JSON.stringify(ev) });
    act(() => {
      emit({ type: 'message', bot: 'scout', message: { id: 'm9', role: 'assistant', content: 'Found it.', ts: 5 } });
      emit({ type: 'state', bot: 'scout', status: 'idle', label: '', since: 5 });
    });
    expect(await screen.findByText('Found it.')).toBeTruthy();
  });

  it('lets you keep bots running, and is honest about what that means', async () => {
    state.bots = [bot()];
    render(<BotsApp />);
    fireEvent.click(await screen.findByRole('button', { name: 'Always on' }));
    expect(await screen.findByText(/can't run while it is off/)).toBeTruthy();
    expect((screen.getByRole('switch', { name: 'Start when I sign in' }) as HTMLButtonElement).disabled).toBe(true);  // not the installed app
    const keep = screen.getByRole('switch', { name: 'Keep running when I close the window' });
    expect(keep.getAttribute('aria-checked')).toBe('false');
    fireEvent.click(keep);
    await waitFor(() => expect(keep.getAttribute('aria-checked')).toBe('true'));
    expect(calls.find((c) => c.url === '/api/bots/background' && c.method === 'POST')?.body).toEqual({ keepRunning: true });
    expect(screen.queryByRole('button', { name: 'Stop bots and quit' })).toBeNull();
  });

  it('renders bot text safely', () => {
    expect(toHtml('<img src=x onerror=alert(1)>')).toBe('<p>&lt;img src=x onerror=alert(1)&gt;</p>');
    expect(toHtml('# Title\n- one\n- two\n\nSee [docs](https://a.b/c).')).toBe(
      '<h4>Title</h4><ul><li>one</li><li>two</li></ul><p>See <a href="https://a.b/c" target="_blank" rel="noreferrer noopener">docs</a>.</p>');
    expect(toHtml('[x](javascript:alert(1))')).not.toContain('<a');
    expect(toHtml(['Output:', '```', '$ echo <b>', '```', 'Done.'].join('\n'))).toBe('<p>Output:</p><pre>$ echo &lt;b&gt;</pre><p>Done.</p>');
  });
});
