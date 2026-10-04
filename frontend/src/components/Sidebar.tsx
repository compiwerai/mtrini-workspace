import React from 'react';
import { I } from './Icon';

export type Nav = 'thread' | 'files' | 'images' | 'mcp' | 'automations' | 'skills' | 'settings';
export type ThreadSummary = { id: string; title: string; updated: number; messages: number; preview: string; workspace?: string };

export function relTime(ts: number): string {
  const d = Date.now() / 1000 - ts;
  if (d < 3600) return `${Math.max(1, Math.round(d / 60))}m`;
  if (d < 86400) return `${Math.round(d / 3600)}h`;
  return `${Math.round(d / 86400)}d`;
}

export default function Sidebar({ nav, go, threads, activeThread, onThread, onNew, onDelete, onRename, workspace, onPickWorkspace }: {
  nav: Nav; go: (n: Nav) => void; threads: ThreadSummary[];
  activeThread: string | null; onThread: (id: string) => void; onNew: () => void;
  onDelete: (id: string) => void; onRename: (id: string, title: string) => void;
  workspace: string | null; onPickWorkspace: () => void;
}) {
  return (
    <aside className="side" aria-label="Workspace sidebar">
      <div className="traffic" aria-hidden="true"><i style={{ background: '#e5605e' }} /><i style={{ background: '#e5a63d' }} /><i style={{ background: '#34c98e' }} /></div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 14px 2px', fontWeight: 700, fontSize: 12 }}>
        <img src="/logo.png" alt="" width={18} height={18} />MTRINI
      </div>
      <div style={{ padding: '6px 8px 2px' }}>
        <button className="wsbtn" onClick={onPickWorkspace} title="Choose working folder">
          {I.folder()}<span className="wsname">{workspace ? workspace.split(/[/\\]/).filter(Boolean).pop() : 'Choose folder…'}</span>{I.chev()}
        </button>
      </div>
      <nav className="nav">
        <button onClick={onNew}>{I.plus()} New thread</button>
        <button className={nav === 'images' ? 'on' : ''} onClick={() => go('images')}>{I.image()} Images</button>
        <button className={nav === 'mcp' ? 'on' : ''} onClick={() => go('mcp')}>{I.plug()} MCP</button>
        <button className={nav === 'automations' ? 'on' : ''} onClick={() => go('automations')}>{I.clock()} Automations</button>
        <button className={nav === 'skills' ? 'on' : ''} onClick={() => go('skills')}>{I.spark()} Skills</button>
        <div className="sec"><span>Threads</span></div>
        {threads.map((t) => (
          <div key={t.id} className={`trow ${activeThread === t.id ? 'on' : ''}`}>
            <button className="tmain" onClick={() => onThread(t.id)} title={t.preview}>
              <span className="threaditem"><span>{t.title}</span><small>{t.updated ? relTime(t.updated) : ''}</small></span>
            </button>
            <span className="tact">
              <button title="Rename" onClick={() => { const v = prompt('Rename thread', t.title); if (v !== null) onRename(t.id, v); }}>{I.pencil()}</button>
              <button title="Delete" onClick={() => { if (confirm(`Delete "${t.title}"?`)) onDelete(t.id); }}>{I.trash()}</button>
            </span>
          </div>
        ))}
        {threads.length === 0 && <div style={{ color: 'var(--faint)', fontSize: 12, padding: '2px 9px' }}>No threads yet.</div>}
        <button className={nav === 'files' ? 'on' : ''} onClick={() => go('files')}>{I.folder()} Files</button>
      </nav>
      <div className="sidefoot">
        <div className="nav"><button className={nav === 'settings' ? 'on' : ''} onClick={() => go('settings')}>{I.gear()} Settings</button></div>
      </div>
    </aside>
  );
}
