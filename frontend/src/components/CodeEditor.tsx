import Editor from '@monaco-editor/react';
import React, { useEffect, useRef, useState } from 'react';
import { api } from '../api/client';
import { loadSettings } from '../lib/settings';

function isLight() {
  const t = document.documentElement.dataset.theme;
  return t === 'light';
}

export default function CodeEditor({ path, onSaved }: { path: string; onSaved: () => void }) {
  const [value, setValue] = useState('');
  const [dirty, setDirty] = useState(false);
  const edRef = useRef<any>(null);
  const monRef = useRef<any>(null);

  const applyPrefs = () => {
    const ed = edRef.current;
    if (!ed) return;
    const s = loadSettings();
    ed.updateOptions({
      fontSize: s.editorFontSize,
      minimap: { enabled: s.minimap },
      wordWrap: s.wordWrap ? 'on' : 'off',
    });
    try { monRef.current?.editor.setTheme(isLight() ? 'vs' : 'vs-dark'); } catch { /* ignore */ }
  };

  useEffect(() => {
    let dead = false;
    api.execTool('read_file', { path }).then((r) => {
      if (!dead && r.ok) { setValue(r.output.content || ''); setDirty(false); }
    }).catch(() => {});
    return () => { dead = true; };
  }, [path]);

  useEffect(() => {
    const h = () => applyPrefs();
    window.addEventListener('mtrini:ui-changed', h);
    return () => window.removeEventListener('mtrini:ui-changed', h);
  }, []);

  const save = async () => {
    await api.execTool('write_file', { path, content: value });
    setDirty(false);
    onSaved();
  };

  const lang = path.endsWith('.py') ? 'python' : path.endsWith('.md') ? 'markdown'
    : path.endsWith('.json') ? 'json' : path.endsWith('.html') ? 'html'
    : path.endsWith('.css') ? 'css' : 'typescript';
  const s0 = loadSettings();

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div className="row" style={{ padding: '4px 8px', background: 'var(--bg2)' }}>
        <span style={{ fontFamily: 'var(--mono)' }}>{path}{dirty ? ' ●' : ''}</span>
        <span style={{ flex: 1 }} />
        <button className="btn" onClick={save}>Save (Ctrl+S)</button>
      </div>
      <div style={{ flex: 1 }}>
        <Editor
          height="100%"
          language={lang}
          theme={isLight() ? 'vs' : 'vs-dark'}
          value={value}
          onChange={(v) => { setValue(v || ''); setDirty(true); }}
          options={{ minimap: { enabled: s0.minimap }, fontSize: s0.editorFontSize, automaticLayout: true, wordWrap: s0.wordWrap ? 'on' : 'off' }}
          onMount={(ed, mon) => {
            edRef.current = ed;
            monRef.current = mon;
            ed.addCommand(mon.KeyMod.CtrlCmd | mon.KeyCode.KeyS, () => save());
            // Right-click on a selection: hand it to the agent with the file and line numbers.
            const ask = (verb: string) => () => {
              const sel = ed.getSelection();
              const model = ed.getModel();
              if (!sel || !model) return;
              const code = sel.isEmpty() ? model.getLineContent(sel.startLineNumber) : model.getValueInRange(sel);
              const where = `${path}:${sel.startLineNumber}${sel.endLineNumber !== sel.startLineNumber ? `-${sel.endLineNumber}` : ''}`;
              const fence = code.includes('```') ? '````' : '```';
              window.dispatchEvent(new CustomEvent('mtrini:ask', { detail: `${verb} (${where}):

${fence}${lang}
${code}
${fence}
` }));
            };
            [
              ['mtrini.explain', 'Mtrini: Explain this code', 'Explain what this code does and anything surprising in it'],
              ['mtrini.fix', 'Mtrini: Find and fix bugs here', 'Find bugs in this code and fix them'],
              ['mtrini.tests', 'Mtrini: Write tests for this', "Write tests for this code, following the project's existing test setup"],
              ['mtrini.refactor', 'Mtrini: Refactor this', 'Refactor this code for clarity without changing behaviour'],
              ['mtrini.ask', 'Mtrini: Ask about this…', 'About this code'],
            ].forEach(([id, label, verb], i) => ed.addAction({
              id, label, contextMenuGroupId: '0_mtrini', contextMenuOrder: i + 1, run: ask(verb),
              ...(id === 'mtrini.ask' ? { keybindings: [mon.KeyMod.CtrlCmd | mon.KeyMod.Shift | mon.KeyCode.KeyL] } : {}),
            }));
            applyPrefs();
          }}
        />
      </div>
    </div>
  );
}
