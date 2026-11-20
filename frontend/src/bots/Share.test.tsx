import React from 'react';
import { act, cleanup, configure, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import BotsApp from './BotsApp';
import { cardContent, fit, mask, plain, whatsappLink, wrap, xLink } from './card';

configure({ asyncUtilTimeout: 5000 });

const bot = (over: Record<string, unknown> = {}) => ({
  id: 'scout', name: 'Scout', role: 'Researcher', instructions: '', provider: 'free', model: 'm', effort: 'off', color: '#f0892b', mascot: 'fennec',
  created: 1, paused: false, session: 1, state: { status: 'idle', label: '', since: 0 }, busy: false, folder: 'C:/bots/scout/files',
  routines: 1, unread: 0, waiting: 0, ...over,
});
const REPLY = 'Scout found 3 AI stories for you\n- A new open model ships - https://www.example.com/a\n- [Chips get cheaper](https://news.example.org/b)\n- Write to me@mail.com';
const RECIPE = { mtriniBot: 1, name: 'Compass', role: 'Job scout', instructions: 'Find openings that fit profile.md.', mascot: 'gecko', color: '#26b97a',
  routines: [{ title: 'New openings', prompt: 'x', kind: 'daily', time: '10:00' }] };

type Call = { url: string; method: string; body: any };
let calls: Call[] = [];
let state: { bots: any[]; inbox: any[]; conversation: any[]; first: any };
let stream: { onmessage: ((m: { data: string }) => void) | null } | null = null;

beforeEach(() => {
  calls = [];
  state = { bots: [], inbox: [], conversation: [], first: { state: 'none' } };
  vi.stubGlobal('EventSource', class { onmessage = null; onerror = null; constructor() { stream = this as any; } close() {} });
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null);  // jsdom has no canvas
  vi.spyOn(HTMLCanvasElement.prototype, 'toDataURL').mockReturnValue('data:image/png;base64,iVBORw0KGgo=');
  vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo, init?: RequestInit) => {
    const url = String(input);
    const method = (init?.method || 'GET').toUpperCase();
    const body = init?.body ? JSON.parse(String(init.body)) : null;
    calls.push({ url, method, body });
    const ok = (data: unknown) => ({ ok: true, status: 200, json: async () => data }) as Response;
    const bad = (detail: string) => ({ ok: false, status: 400, json: async () => ({ detail }) }) as Response;
    if (url === '/api/bots' && method === 'GET') return ok({ bots: state.bots, unread: 0, browser: true, colors: [] });
    if (url === '/api/bots/inbox') return ok({ items: state.inbox, unread: 0 });
    if (url === '/api/bots/first-run') return ok(state.first);
    if (url === '/api/bots/first-run/start') { state.first = { ...state.first, state: 'running' }; return ok(state.first); }
    if (url === '/api/bots/first-run/seen') { state.first = { ...state.first, state: 'seen' }; return ok(state.first); }
    if (url === '/api/bots/cards') return ok({ path: 'C:/Users/me/Pictures/Mtrini Bots/Scout card.png', folder: 'C:/Users/me/Pictures/Mtrini Bots' });
    if (url === '/api/bots/open') return ok({ ok: true });
    if (url === '/api/bots/recipes/preview') return body.text.includes('#') ? ok({ recipe: RECIPE }) : bad('That is not a Mtrini Bots recipe.');
    if (url === '/api/bots/recipes/import') { const b = bot({ id: 'compass', name: 'Compass', mascot: 'gecko' }); state.bots.push(b); return ok(b); }
    if (url === '/api/bots/scout/recipe') return ok({ recipe: RECIPE, link: 'https://compiwer.ai/bots/r#eyJtdHJpbmlCb3QiOjF9' });
    if (url === '/api/bots/templates') return ok({ templates: [{ key: 'blank', name: '', role: '', instructions: '', mascot: '', routines: [] }] });
    if (url === '/api/providers') return ok({ providers: [{ id: 'free', configured: true, kind: 'chat', free: true }] });
    if (url.startsWith('/api/models')) return ok({ models: [{ id: 'm', label: 'Mtrini Free' }] });
    if (url.endsWith('/conversation')) return ok({ messages: state.conversation, state: { status: 'idle', label: '', since: 0 }, busy: false });
    return ok({});
  }));
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks(); });

describe('cards', () => {
  it('turns a reply into a headline and a few plain lines', () => {
    const c = cardContent('Scout', REPLY);
    expect(c.headline).toBe('Scout found 3 AI stories for you');
    expect(c.lines).toEqual(['A new open model ships (example.com)', 'Chips get cheaper', 'Write to [hidden]']);
    expect(c.hidden).toEqual(['an email address']);
    expect(cardContent('Herald', 'Here is your digest:\n1. One\n2. Two').headline).toBe('Herald found 2 things for you');
    expect(cardContent('Atlas', 'Nothing new.', 'Morning briefing')).toMatchObject({ headline: 'Nothing new.', lines: [] });
    expect(cardContent('Atlas', '- only one', 'Morning briefing').headline).toBe('Atlas: Morning briefing');
    expect(cardContent('Quill', 'One thing here. Two things here. Three things here. Four things here. Five things here now.').lines).toHaveLength(4);
  });

  it('hides what looks personal and leaves the rest', () => {
    expect(mask('Call +212 6 12 34 56 78 or see C:\\Users\\ayham\\cv.pdf').text).toBe('Call [hidden] or see [hidden]');
    expect(mask('Due 2026-11-28, 3 items, 120 MAD').hidden).toEqual([]);
    expect(plain('**Big** news: `x` — <https://www.a.com/b?c=1>')).toBe('Big news: x (a.com)');
  });

  it('wraps and fits text to the card', () => {
    const measure = (s: string) => s.length;
    expect(wrap('one two three four', 9, measure)).toEqual(['one two', 'three', 'four']);
    expect(wrap('abcdefghij', 4, measure)).toEqual(['abcd', 'efgh', 'ij']);
    expect(fit('one two three four', 9, 2, measure)).toEqual(['one two', 'three…']);
  });

  it('makes share links with the text and the site', () => {
    expect(xLink('Scout found 3 jobs')).toBe('https://x.com/intent/post?text=Scout%20found%203%20jobs.%20Made%20with%20Mtrini%20Bots%3A%20free%2C%20open-source%20AI%20bots%20that%20run%20on%20your%20PC.&url=https%3A%2F%2Fcompiwer.ai%2Fbots');
    expect(decodeURIComponent(whatsappLink('Hi!'))).toContain('Hi. Made with Mtrini Bots: free, open-source AI bots that run on your PC. https://compiwer.ai/bots');
  });
});

describe('sharing in the app', () => {
  it('runs a first job on launch and offers its card', async () => {
    state.bots = [bot()];
    state.first = { state: 'pending', bot: 'scout', botName: 'Scout', provider: 'free' };
    state.conversation = [{ id: 'u1', role: 'user', content: 'Show me what you can do', ts: 100 }];
    render(<BotsApp />);
    expect(await screen.findByText("Scout's first job.")).toBeTruthy();
    expect(calls.some((c) => c.url === '/api/bots/first-run/start' && c.method === 'POST')).toBe(true);
    expect(screen.getByText(/free built-in model: no key, no setup/)).toBeTruthy();

    const reply = { id: 'm1', role: 'assistant', content: REPLY, ts: 109 };
    state.conversation.push(reply);
    state.first = { state: 'done', bot: 'scout', botName: 'Scout', provider: 'free', message: reply };
    act(() => { stream!.onmessage!({ data: JSON.stringify({ type: 'message', bot: 'scout', message: reply }) }); });
    expect(await screen.findByText('Done in 9 seconds.')).toBeTruthy();
    expect(screen.getByRole('img', { name: 'Card: Scout found 3 AI stories for you' })).toBeTruthy();

    fireEvent.click(screen.getByRole('button', { name: 'Share this card' }));
    expect(await screen.findByRole('dialog', { name: 'Share as a card' })).toBeTruthy();
    expect((screen.getByLabelText('Headline') as HTMLInputElement).value).toBe('Scout found 3 AI stories for you');
    expect((screen.getByLabelText('Lines') as HTMLTextAreaElement).value).not.toContain('me@mail.com');
    expect(screen.getByText(/Hidden because it looked personal: an email address/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Headline'), { target: { value: 'Scout read the news for me' } });
    expect(screen.getAllByRole('img', { name: 'Card: Scout read the news for me' })).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: 'Save image' }));
    await waitFor(() => expect(calls.find((c) => c.url === '/api/bots/cards')?.body).toEqual({ png: 'data:image/png;base64,iVBORw0KGgo=', name: 'Scout' }));
    expect(await screen.findByText('C:/Users/me/Pictures/Mtrini Bots/Scout card.png')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Post on X' }));
    await waitFor(() => expect(calls.find((c) => c.url === '/api/bots/open')?.body.url).toContain('Scout%20read%20the%20news%20for%20me'));
    fireEvent.click(screen.getByRole('button', { name: 'WhatsApp' }));
    await waitFor(() => expect(calls.filter((c) => c.url === '/api/bots/open')[1]?.body.url).toMatch(/^https:\/\/wa\.me\//));
    fireEvent.keyDown(window, { key: 'Escape' });
    fireEvent.click(screen.getByRole('button', { name: 'Done' }));
    await waitFor(() => expect(screen.queryByText('Done in 9 seconds.')).toBeNull());
    expect(calls.some((c) => c.url === '/api/bots/first-run/seen')).toBe(true);
  }, 20000);

  it('says so when the first job fails, and tries again', async () => {
    state.bots = [bot()];
    state.first = { state: 'failed', bot: 'scout', botName: 'Scout', provider: 'free', message: { id: 'e', role: 'assistant', content: 'Allowance used.', ts: 2, error: true } };
    render(<BotsApp />);
    expect(await screen.findByText('The free model could not answer just now.')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByText("Scout's first job.")).toBeTruthy();
  });

  it('shares an inbox report as a card', async () => {
    state.bots = [bot()];
    state.inbox = [{ id: 'b1', bot: 'scout', botName: 'Scout', botColor: '#f0892b', botMascot: 'fennec', kind: 'briefing', title: "What's new", body: '- One\n- Two', ts: 10, read: true }];
    render(<BotsApp />);
    fireEvent.click(await screen.findByRole('button', { name: /What's new/ }));
    fireEvent.click(screen.getByRole('button', { name: 'Share as card' }));
    expect((await screen.findByLabelText('Headline') as HTMLInputElement).value).toBe('Scout found 2 things for you');
    expect(screen.queryByText(/looked personal/)).toBeNull();
  });

  it('shares a bot as a recipe link', async () => {
    state.bots = [bot()];
    render(<BotsApp />);
    fireEvent.click(await screen.findByRole('button', { name: /Scout/ }));
    fireEvent.click(await screen.findByRole('tab', { name: 'Settings' }));
    fireEvent.click(screen.getByRole('button', { name: 'Share recipe' }));
    await waitFor(() => expect((screen.getByLabelText('Recipe link') as HTMLInputElement).value).toBe('https://compiwer.ai/bots/r#eyJtdHJpbmlCb3QiOjF9'));
    expect(screen.getByText(/Not the memory, files, conversation or model/)).toBeTruthy();
  });

  it('adds a bot from a pasted recipe after showing what it will do', async () => {
    state.bots = [bot()];
    render(<BotsApp />);
    fireEvent.click(await screen.findByRole('button', { name: 'New bot' }));
    fireEvent.click(await screen.findByRole('button', { name: 'From a recipe' }));
    const box = await screen.findByLabelText('Recipe link');
    fireEvent.change(box, { target: { value: 'not a recipe' } });
    fireEvent.click(screen.getByRole('button', { name: 'Preview' }));
    expect(await screen.findByText('That is not a Mtrini Bots recipe.')).toBeTruthy();
    fireEvent.change(box, { target: { value: 'https://compiwer.ai/bots/r#eyJ9' } });
    fireEvent.click(screen.getByRole('button', { name: 'Preview' }));
    expect(await screen.findByText('Find openings that fit profile.md.')).toBeTruthy();
    expect(screen.getByText('Routines, switched off until you turn them on')).toBeTruthy();
    expect(screen.getByText('New openings')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Add Compass' }));
    await waitFor(() => expect(calls.find((c) => c.url === '/api/bots/recipes/import')?.body).toEqual({ text: 'https://compiwer.ai/bots/r#eyJ9' }));
    expect(await screen.findByText(/Compass is ready/)).toBeTruthy();
  });
});
