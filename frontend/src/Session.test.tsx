import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import App from './App';
import ThreadView, { toolLabel } from './components/ThreadView';

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

describe('agent 0.8 UI', () => {
  const base = {
    messages: [] as any[], busy: false, status: '', pending: null, files: [], branch: 'main', model: 'local:m',
    setModel: () => {}, onSend: () => {}, onCommand: () => {}, onStop: () => {}, onApprove: () => {}, onDeny: () => {},
    needsSetup: false, onGoSettings: () => {}, threadWs: null, onPickThreadFolder: () => {}, effort: 'off',
    setEffort: () => {}, project: 'demo', seed: null,
  };

  it('offers plan mode and the new slash commands', () => {
    render(<ThreadView {...base} />);
    expect(screen.getByLabelText('Permission mode').textContent).toContain('Plan mode');
    fireEvent.change(screen.getByLabelText('Message the agent'), { target: { value: '/' } });
    const menu = screen.getByRole('listbox').textContent || '';
    for (const c of ['/compact', '/init', '/agents', '/permissions']) expect(menu).toContain(c);
  });

  it('shows the plan card and sends the decision', () => {
    const decisions: any[] = [];
    render(<ThreadView {...base} plan={'1. Edit `a.ts`'} onPlan={(d) => decisions.push(d)} />);
    fireEvent.click(screen.getByText('Approve, auto-accept edits'));
    fireEvent.change(screen.getByLabelText('Plan feedback'), { target: { value: 'add tests' } });
    fireEvent.click(screen.getByText('Keep planning'));
    expect(decisions).toEqual([{ decision: 'approve', mode: 'auto' }, { decision: 'reject', feedback: 'add tests' }]);
  });

  it('renders todos, diffs, always-allow and rewind', () => {
    const calls: any[] = [];
    render(<ThreadView {...base}
      todos={[{ content: 'Read code', status: 'completed' }, { content: 'Fix bug', status: 'in_progress' }]}
      messages={[{ role: 'user', text: 'fix it', turn: 3 },
        { role: 'tool', text: 'edit_file', tool: 'edit_file', args: { path: 'a.ts' }, status: 'ok', diff: ['--- a', '+++ b', '@@ -1 +1 @@', '-old', '+new'] }]}
      pending={{ tool: 'execute_command', args: { command: 'npm test' }, rule: 'execute_command:npm test' }}
      onApprove={(always) => calls.push(['approve', always])} onRewind={(t) => calls.push(['rewind', t])} />);
    expect(screen.getByLabelText('Agent task list').textContent).toContain('1/2');
    const diff = screen.getByLabelText('Changes');
    expect(diff.querySelector('.add')?.textContent).toContain('+new');
    expect(diff.querySelector('.del')?.textContent).toContain('-old');
    fireEvent.click(screen.getByText(/Always allow/));
    fireEvent.click(screen.getByLabelText('Rewind to before this message'));
    expect(calls).toEqual([['approve', true], ['rewind', 3]]);
  });
});
