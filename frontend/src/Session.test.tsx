import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import App from './App';
import { toolLabel } from './components/ThreadView';

describe('session composer', () => {
  it('opens the slash menu with built-in commands', () => {
    render(<App />);
    const box = screen.getByLabelText('Message the agent');
    fireEvent.change(box, { target: { value: '/' } });
    const menu = screen.getByRole('listbox', { name: /commands and skills/i });
    expect(menu.textContent).toContain('/help');
    expect(menu.textContent).toContain('/skills');
    fireEvent.change(box, { target: { value: '/he' } });
    expect(screen.getByRole('listbox').textContent).toContain('/help');
    expect(screen.getByRole('listbox').textContent).not.toContain('/skills');
  });

  it('labels tool calls in plain words', () => {
    expect(toolLabel('read_file', { path: 'src/App.tsx' })).toEqual({ verb: 'Read', target: 'src/App.tsx' });
    expect(toolLabel('execute_command', { command: 'npm test' })).toEqual({ verb: 'Run', target: 'npm test' });
    expect(toolLabel('move_file', { src: 'a.ts', dst: 'b.ts' }).target).toBe('a.ts → b.ts');
    expect(toolLabel('custom_tool', {}).verb).toBe('Custom tool');
  });
});
