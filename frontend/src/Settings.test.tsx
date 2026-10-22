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
