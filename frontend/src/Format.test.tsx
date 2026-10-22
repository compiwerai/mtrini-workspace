import { describe, expect, it } from 'vitest';
import { formatToolOutput } from './App';
import { parseStatus } from './components/DiffPanel';

describe('git status parsing', () => {
  it('keeps porcelain columns and skips the branch header', () => {
    const files = parseStatus('## master\n M src/pricing.py\nA  new.ts\n?? .mtrini/\r\n');
    expect(files).toEqual([
      { code: ' M', path: 'src/pricing.py' },
      { code: 'A ', path: 'new.ts' },
      { code: '??', path: '.mtrini/' },
    ]);
  });
});

describe('tool output', () => {
  it('shows command output as text with its exit code', () => {
    expect(formatToolOutput({ exitCode: 0, stdout: '..  [100%]\r\n2 passed in 0.02s\r\n', stderr: '' }))
      .toBe('..  [100%]\n2 passed in 0.02s\nexit code 0');
  });
  it('shows file content directly', () => {
    expect(formatToolOutput({ path: 'a.py', content: 'x = 1\r\n' })).toBe('x = 1\n');
  });
  it('falls back to JSON', () => {
    expect(formatToolOutput({ a: 1 })).toBe('{\n  "a": 1\n}');
  });
});
