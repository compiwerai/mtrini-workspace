import React, { useEffect, useState } from 'react';
import { api, getRecents } from '../api/client';
import { I } from './Icon';

export default function WorkspacePicker({ current, onClose, onPick }: {
  current: string | null; onClose: () => void; onPick: (path: string) => void;
}) {
  const [path, setPath] = useState(current || '');
  const [dirs, setDirs] = useState<{ name: string; path: string }[]>([]);
  const [parent, setParent] = useState('');
  const [err, setErr] = useState('');

  const load = async (p?: string) => {
    setErr('');
    try {
      const r = await api.browse(p);
      setPath(r.path);
      setParent(r.parent);
      setDirs(r.dirs || []);
    } catch (e: any) { setErr(String(e.message || e)); }
  };

  useEffect(() => { load(current || undefined); }, []); // eslint-disable-line

  return (
    <div className="modal" onClick={onClose} role="dialog" aria-label="Choose workspace folder">
      <div className="sheet" style={{ width: 520 }} onClick={(e) => e.stopPropagation()}>
        <strong>Choose workspace folder</strong>
        <p style={{ color: 'var(--muted)', fontSize: 12 }}>The agent works inside this folder. Threads, skills and models stay per-folder.</p>
        <div className="row">
          <input className="t" value={path} onChange={(e) => setPath(e.target.value)} placeholder="C:\code\my-project" aria-label="Folder path" />
          <button className="btn" onClick={() => load(path || undefined)}>Go</button>
        </div>
        {err && <div style={{ color: 'var(--danger)', fontSize: 12 }}>{err}</div>}
        <div style={{ maxHeight: 220, overflowY: 'auto', margin: '8px 0', border: '1px solid var(--border)', borderRadius: 8 }}>
          {parent && parent !== path && <div className="file" onClick={() => load(parent)}>{I.chev()} ..</div>}
          {dirs.map((d) => <div key={d.path} className="file" onClick={() => load(d.path)}>{I.folder()} {d.name}</div>)}
        </div>
        {getRecents().length > 0 && (
          <>
            <label className="f">Recent</label>
            {getRecents().map((r) => <div key={r} className="file" onClick={() => onPick(r)}>{I.clock()} {r}</div>)}
          </>
        )}
        <div className="row" style={{ marginTop: 10 }}>
          <button className="btn primary" onClick={() => path && onPick(path)}>Use this folder</button>
          <button className="btn" onClick={onClose}>Cancel</button>
        </div>
      </div>
    </div>
  );
}
