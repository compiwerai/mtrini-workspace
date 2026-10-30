import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it } from 'vitest';
import SettingsPanel from './components/SettingsPanel';
import { loadSettings } from './lib/settings';

describe('settings', () => {
  beforeEach(() => localStorage.removeItem('mtrini.ui'));

  it('saves chat settings and applies layout settings to the document', () => {
    render(<SettingsPanel onToast={() => {}} />);
    fireEvent.click(screen.getByRole('tab', { name: 'Chat' }));
    fireEvent.click(screen.getByRole('switch', { name: 'Expand tool output' }));
    expect(loadSettings().toolsExpanded).toBe(true);

    fireEvent.change(screen.getByLabelText('Send messages with'), { target: { value: 'mod-enter' } });
    expect(loadSettings().sendKey).toBe('mod-enter');

    fireEvent.click(screen.getByRole('tab', { name: 'Appearance' }));
    fireEvent.change(screen.getByLabelText('Conversation width'), { target: { value: 'wide' } });
    expect(document.documentElement.dataset.width).toBe('wide');
  });

  it('turns skills off for the agent', () => {
    render(<SettingsPanel onToast={() => {}} />);
    fireEvent.click(screen.getByRole('tab', { name: 'Agent' }));
    fireEvent.click(screen.getByRole('switch', { name: 'Use skills' }));
    expect(loadSettings().useSkills).toBe(false);
  });
});

describe('custom providers', () => {
  it('adds your own OpenAI-compatible provider and shows key fields for every key provider', async () => {
    const { vi } = await import('vitest');
    const { fireEvent, render, screen, waitFor } = await import('@testing-library/react');
    const SettingsPanel = (await import('./components/SettingsPanel')).default;
    let providers: any[] = [
      { id: 'local', label: 'Local server', needsKey: false, fields: ['baseUrl', 'model'], configured: true, kind: 'chat' },
      { id: 'heabsy', label: 'Heabsy (EU)', needsKey: true, configured: false, kind: 'chat' },
    ];
    const posted: any[] = [];
    vi.stubGlobal('fetch', vi.fn(async (url: string, init?: any) => {
      const u = new URL(url, 'http://x');
      if (u.pathname === '/api/providers/custom' && init?.method === 'POST') {
        const b = JSON.parse(init.body); posted.push(b);
        providers = [...providers, { id: 'custom-orcarouter', label: b.label, baseUrl: b.baseUrl, custom: true, configured: true, kind: 'chat' }];
        return new Response(JSON.stringify({ id: 'custom-orcarouter', label: b.label, baseUrl: b.baseUrl }));
      }
      if (u.pathname === '/api/providers') return new Response(JSON.stringify({ providers }));
      return new Response('{}');
    }));
    render(<SettingsPanel onToast={() => {}} />);
    fireEvent.click(screen.getByRole('tab', { name: 'Providers' }));
    const select = (await screen.findAllByRole('combobox'))[0] as HTMLSelectElement;
    await waitFor(() => expect(select.querySelectorAll('option').length).toBe(2));
    fireEvent.change(select, { target: { value: 'heabsy' } });
    expect(screen.getByPlaceholderText('sk-…')).toBeTruthy(); // Heabsy now gets a key field
    fireEvent.change(screen.getByLabelText('Provider name'), { target: { value: 'OrcaRouter' } });
    fireEvent.change(screen.getByLabelText('Provider base URL'), { target: { value: 'https://api.orcarouter.ai/v1' } });
    fireEvent.click(screen.getByText('Add provider'));
    await waitFor(() => expect(screen.getByLabelText('Remove OrcaRouter')).toBeTruthy());
    expect(posted[0]).toMatchObject({ label: 'OrcaRouter', baseUrl: 'https://api.orcarouter.ai/v1' });
    vi.unstubAllGlobals();
  });
});
