import React, { useCallback, useEffect, useState } from 'react';
import { api } from '../api/client';
import { I } from './Icon';

function parseStatus(porcelain: string): { path: string; code: string }[] {
  return porcelain.split('\n').map((l) => l.trim()).filter(Boolean).map((l) => ({
    code: l.slice(0, 2), path: l.slice(3).replace(/^"(.+)"$/, '$1'),
  }));
}

export default function DiffPanel({ tick }: { tick: number }) {
  const [tab, setTab] = useState<'unstaged' | 'staged'>('unstaged');
  const [files, setFiles] = useState<{ path: string; code: string }[]>([]);
  const [diff, setDiff] = useState('');
  const [open, setOpen] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const s = await api.gitStatus();
      const porcelain = s.output?.stdout || '';
      const all = parseStatus(porcelain);
      const staged = all.filter((f) => f.code[0] !== ' ' && f.code[0] !== '?');
      const unstaged = all.filter((f) => f.code[1] !== ' ' || f.code.startsWith('??'));
      setFiles(tab === 'staged' ? staged : unstaged);
      const d = tab === 'staged' ? await api.gitDiffCached() : await api.gitDiff();
      setDiff((d.output?.stdout || '').slice(0, 12000));
    } catch { setFiles([]); setDiff(''); }
  }, [tab]);

  useEffect(() => { load(); }, [load, tick]);

  const stage = async (paths: string[]) => {
    try { await api.gitStage(paths); load(); } catch { /* surface on next load */ }
  };

  return (
    <aside className="diffpanel" aria-label="Uncommitted changes">
      <header><strong>Uncommitted changes</strong><span className="row">
        {tab === 'unstaged' && files.length > 0 && <button className="btn" onClick={() => stage(files.map((f) => f.path))} title="Stage all">Stage all</button>}
        <button className="btn iconbtn" onClick={load} title="Refresh">{I.refresh()}</button></span></header>
      <div className="dtabs">
        <button className={tab === 'unstaged' ? 'on' : ''} onClick={() => setTab('unstaged')}>Unstaged</button>
        <button className={tab === 'staged' ? 'on' : ''} onClick={() => setTab('staged')}>Staged</button>
      </div>
      <div className="diffscroll">
        {files.length === 0 ? (
          <div className="empty"><b>No {tab} changes</b>Code changes will appear here</div>
        ) : (
          <>
            {files.map((f) => (
              <div className="dfile" key={f.path}>
                <button onClick={() => setOpen(open === f.path ? null : f.path)}>
                  <span className={`st st-${f.code.trim()[0] || 'q'}`}>{f.code}</span> {f.path}
                </button>
                {tab === 'unstaged' && !f.code.startsWith('??') && (
                  <div style={{ padding: '0 10px 8px', background: 'var(--bg3)' }}>
                    <button className="btn" onClick={() => stage([f.path])}>Stage</button>
                  </div>
                )}
                {open === f.path && (
                  <pre className="difftext">{(diff || '(diff unavailable)').split('\n').map((l, i) => (
                    <span key={i} className={l.startsWith('+') && !l.startsWith('+++') ? 'add' : l.startsWith('-') && !l.startsWith('---') ? 'del' : l.startsWith('@@') ? 'hunk' : ''}>{l}{'\n'}</span>
                  ))}</pre>
                )}
              </div>
            ))}
          </>
        )}
      </div>
    </aside>
  );
}
