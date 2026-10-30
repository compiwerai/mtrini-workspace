import React, { useEffect, useState } from 'react';
import { api } from '../api/client';

export type UpdateStatus = {
  status: 'idle' | 'checking' | 'uptodate' | 'available' | 'downloading' | 'ready' | 'installing' | 'installed' | 'error';
  current: string; latest?: string; url?: string; error?: string; auto: boolean; kind: string;
};

/** Shown when a downloaded update is ready (or, for installs that can't update themselves, available). */
export function UpdateBanner() {
  const [u, setU] = useState<UpdateStatus | null>(null);
  const [hidden, setHidden] = useState(false);
  useEffect(() => {
    const load = () => api.updateStatus().then(setU).catch(() => {});
    load();
    const t = window.setInterval(load, 10 * 60 * 1000);
    return () => window.clearInterval(t);
  }, []);
  if (!u || hidden || !u.latest) return null;
  if (u.status === 'ready') {
    return (
      <div className="updatebar" role="status">
        <span>Mtrini Workspace {u.latest} is ready. It installs when you close the app.</span>
        <button className="btn primary" onClick={() => api.restartToUpdate().catch(() => {})}>Restart to update</button>
        <button className="btn" onClick={() => setHidden(true)}>Later</button>
      </div>
    );
  }
  if (u.status === 'available' && u.kind !== 'source') {
    return (
      <div className="updatebar" role="status">
        <span>Mtrini Workspace {u.latest} is available.</span>
        <a className="btn primary" href={u.url} target="_blank" rel="noreferrer">Download</a>
        <button className="btn" onClick={() => setHidden(true)}>Later</button>
      </div>
    );
  }
  return null;
}

/** Settings → About: automatic updates switch and a manual check. */
export function UpdateSettings() {
  const [u, setU] = useState<UpdateStatus | null>(null);
  useEffect(() => { api.updateStatus().then(setU).catch(() => {}); }, []);
  if (!u) return null;
  const line: Record<string, string> = {
    idle: '', checking: 'Checking…', uptodate: `You have the latest version (${u.current}).`,
    available: `Version ${u.latest} is available.`, downloading: `Downloading ${u.latest}…`,
    ready: `Version ${u.latest} is downloaded and installs when you close the app.`,
    installing: 'Installing…', installed: `Version ${u.latest} installs on the next start.`, error: u.error || 'Update check failed.',
  };
  const check = async () => { setU({ ...u, status: 'checking' }); setU(await api.checkForUpdates().catch(() => ({ ...u, status: 'error' as const }))); };
  return (
    <div className="updatesettings">
      <div className="setrow">
        <div><strong>Update automatically</strong>
          <p className="hint">{u.kind === 'linux-manual'
            ? 'This install (.deb or .tar.gz) can’t update itself; you’ll be told when a new version is out.'
            : 'Downloads new versions in the background and installs them when you close the app.'}</p></div>
        <input type="checkbox" aria-label="Update automatically" checked={u.auto}
          onChange={async (e) => setU(await api.setAutoUpdate(e.target.checked))} />
      </div>
      <div className="row" style={{ marginTop: 8 }}>
        <button className="btn" onClick={check} disabled={u.status === 'checking' || u.status === 'downloading'}>Check for updates</button>
        {u.status === 'ready' && <button className="btn primary" onClick={() => api.restartToUpdate().catch(() => {})}>Restart to update</button>}
        <span className="hint">{line[u.status]}</span>
      </div>
    </div>
  );
}
