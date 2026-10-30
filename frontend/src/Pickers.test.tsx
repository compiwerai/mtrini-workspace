import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import ThreadView from './components/ThreadView';

const providers = [
  { id: 'local', label: 'Local server', configured: false, kind: 'chat' },
  { id: 'openai', label: 'OpenAI', configured: true, kind: 'chat' },
  { id: 'anthropic', label: 'Anthropic', configured: true, kind: 'chat' },
  { id: 'sdwebui', label: 'SD WebUI', configured: true, kind: 'image' },
];
const models: Record<string, any[]> = {
  openai: [{ id: 'gpt-4o', label: 'gpt-4o', capabilities: { reasoning: false } },
    { id: 'gpt-5', label: 'gpt-5', capabilities: { reasoning: true } }],
  anthropic: [{ id: 'claude-opus-5-5', label: 'claude-opus-5-5', capabilities: { reasoning: true } }],
};

function fakeFetch(url: string) {
  const u = new URL(url, 'http://x');
  let body: any = {};
  if (u.pathname === '/api/providers') body = { providers };
  else if (u.pathname === '/api/models') body = { models: models[u.searchParams.get('provider') || ''] || [] };
  else if (u.pathname === '/api/skills') body = { skills: [] };
  return Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { 'content-type': 'application/json' } }));
}

const base = {
  messages: [] as any[], busy: false, status: '', pending: null, files: [], branch: 'main', model: '',
  setModel: () => {}, onSend: () => {}, onCommand: () => {}, onStop: () => {}, onApprove: () => {}, onDeny: () => {},
  needsSetup: false, onGoSettings: () => {}, threadWs: null, onPickThreadFolder: () => {}, effort: 'high',
  setEffort: () => {}, project: 'demo', seed: null,
};

describe('composer pickers', () => {
  beforeEach(() => { localStorage.clear(); vi.stubGlobal('fetch', vi.fn(fakeFetch)); });
  afterEach(() => vi.unstubAllGlobals());

  it('lists only connected chat providers, with a model dropdown and thinking only where supported', async () => {
    const reasoning: boolean[] = [];
    render(<ThreadView {...base} onReasoning={(r) => reasoning.push(r)} />);
    const prov = await screen.findByTestId('provider-select');
    expect([...prov.querySelectorAll('option')].map((o) => o.value)).toEqual(['openai', 'anthropic']);
    const model = screen.getByLabelText('Model') as HTMLSelectElement;
    await waitFor(() => expect(model.value).toBe('gpt-4o'));
    expect(screen.queryByLabelText('Thinking effort')).toBeNull();
    fireEvent.change(model, { target: { value: 'gpt-5' } });
    expect(screen.getByLabelText('Thinking effort')).toBeTruthy();
    expect(reasoning[reasoning.length - 1]).toBe(true);
    expect(JSON.parse(localStorage.getItem('mtrini.chatModel') || '{}')).toEqual({ prov: 'openai', mid: 'gpt-5' });
  });

  it('remembers the last provider and model', async () => {
    localStorage.setItem('mtrini.chatModel', JSON.stringify({ prov: 'anthropic', mid: 'claude-opus-5-5' }));
    render(<ThreadView {...base} />);
    const prov = (await screen.findByTestId('provider-select')) as HTMLSelectElement;
    expect(prov.value).toBe('anthropic');
    await waitFor(() => expect((screen.getByLabelText('Model') as HTMLSelectElement).value).toBe('claude-opus-5-5'));
  });

  it('offers to connect a provider when none is connected', async () => {
    vi.stubGlobal('fetch', vi.fn((u: string) => u.includes('/api/providers')
      ? Promise.resolve(new Response(JSON.stringify({ providers: providers.map((p) => ({ ...p, configured: false })) })))
      : fakeFetch(u)));
    const go = vi.fn();
    render(<ThreadView {...base} onGoSettings={go} />);
    await act(async () => { fireEvent.click(await screen.findByText('Connect a provider')); });
    expect(go).toHaveBeenCalled();
  });
});
