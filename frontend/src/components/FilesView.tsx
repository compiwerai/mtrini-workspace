import React, { useCallback, useEffect, useState } from 'react';
import { api } from '../api/client';
import CodeEditor from './CodeEditor';
import { I } from './Icon';
import TerminalPane from './TerminalPane';

export default function FilesView({ openSignal }: { openSignal: { path: string; n: number } | null }) {
  const [files, setFiles] = useState<{ name: string; type: string }[]>([]);
  const [tabs, setTabs] = useState<string[]>([]);
  const [active, setActive] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const r = await api.execTool('list_directory', { path: '.' });
      if (r.ok) setFiles(r.output.entries || []);
    } catch { /* ignore */ }
  }, []);

  useEffect(() => { refresh(); }, [refresh]);
  useEffect(() => {
    if (openSignal) {
      setTabs((t) => (t.includes(openSignal.path) ? t : [...t, openSignal.path]));
      setActive(openSignal.path);
    }
  }, [openSignal]);

  return (
    <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>
      <div style={{ width: 220, borderRight: '1px solid var(--border)', overflowY: 'auto', padding: 8 }}>
        <div className="row"><strong>Files</strong><span style={{ flex: 1 }} /><button className="btn iconbtn" onClick={refresh} title="Refresh">{I.refresh()}</button></div>
        {files.map((f) => (
          <div key={f.name} className="file" onClick={() => {
            if (f.type !== 'dir') { setTabs((t) => (t.includes(f.name) ? t : [...t, f.name])); setActive(f.name); }
          }}>{f.type === 'dir' ? I.folder() : I.file()} {f.name}</div>
        ))}
      </div>
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        <div className="tabs">
          {tabs.map((t) => (
            <button key={t} className={active === t ? 'on' : ''} onClick={() => setActive(t)}
              onDoubleClick={() => setTabs((x) => x.filter((f) => f !== t))}>{t.split('/').pop()}</button>
          ))}
        </div>
        <div style={{ flex: 1, minHeight: 0 }}>
          {active ? <CodeEditor path={active} onSaved={() => {}} /> : <div style={{ padding: 20, color: 'var(--muted)' }}>Select a file.</div>}
        </div>
        <TerminalPane />
      </div>
    </div>
  );
}
