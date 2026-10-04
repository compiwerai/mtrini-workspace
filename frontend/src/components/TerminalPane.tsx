import React, { useEffect, useState } from 'react';
import { api } from '../api/client';
import { loadSettings } from '../lib/settings';

export default function TerminalPane() {
  const [out, setOut] = useState('$ Mtrini terminal — real backend execution\n');
  const [cmd, setCmd] = useState('');
  const [hist, setHist] = useState<string[]>([]);
  const [fontSize, setFontSize] = useState(loadSettings().terminalFontSize);

  useEffect(() => {
    const h = () => setFontSize(loadSettings().terminalFontSize);
    window.addEventListener('mtrini:ui-changed', h);
    return () => window.removeEventListener('mtrini:ui-changed', h);
  }, []);

  const run = async (c: string) => {
    setOut((o) => o + `\n$ ${c}\n`);
    try {
      const r = await api.termExec(c);
      const d = r.output || r;
      setOut((o) => o + (d.stdout || '') + (d.stderr || '') + `[exit ${d.exitCode ?? '?'}]\n`);
    } catch (e: any) {
      setOut((o) => o + `error: ${e.message}\n`);
    }
  };

  return (
    <div className="term" aria-label="Terminal">
      <pre data-testid="terminal-output" style={{ fontSize }}>{out}</pre>
      <form onSubmit={(e) => { e.preventDefault(); if (cmd.trim()) { run(cmd); setHist((h) => [...h, cmd]); setCmd(''); } }}>
        <span style={{ fontFamily: 'var(--mono)' }}>$</span>
        <input value={cmd} onChange={(e) => setCmd(e.target.value)} placeholder="npm test / git status / pytest …" aria-label="Terminal input" />
        <button className="btn ghost">Run</button>
      </form>
    </div>
  );
}
