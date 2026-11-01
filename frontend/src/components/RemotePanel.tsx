import React, { useEffect, useState } from 'react';
import { api, getWorkspace } from '../api/client';

export type RemoteState = {
  enabled: boolean; signedIn: boolean; connected: boolean; error: string;
  phonesOnline: { id: string; name: string }[];
  paired: { id: string; name: string; pairedAt: number; allowAuto: boolean }[];
  pending: { id: string; name: string; code: string }[];
  projects: string[];
};

const spaced = (code: string) => `${code.slice(0, 3)} ${code.slice(3)}`;

function useRemote(intervalMs: number) {
  const [st, setSt] = useState<RemoteState | null>(null);
  useEffect(() => {
    let live = true;
    const load = () => api.remote().then((s) => { if (live) setSt(s); }).catch(() => {});
    load();
    const t = window.setInterval(load, intervalMs);
    return () => { live = false; window.clearInterval(t); };
  }, [intervalMs]);
  return [st, setSt] as const;
}

/** Settings → Account: let your phone use this PC. */
export default function RemotePanel({ onToast }: { onToast: (s: string) => void }) {
  const [st, setSt] = useRemote(3000);
  if (!st) return null;
  const ws = getWorkspace();
  const shared = ws ? st.projects.some((p) => p.toLowerCase() === ws.toLowerCase().replace(/[\\/]+$/, '')) : false;
  const act = async (fn: () => Promise<RemoteState>, msg?: string) => {
    try { setSt(await fn()); if (msg) onToast(msg); } catch (e: any) { onToast(String(e.message || e)); }
  };
  return (
    <div className="remote">
      <h3>Remote access</h3>
      <div className="setrow">
        <div>
          <strong>Use this PC from your phone</strong>
          <p className="hint">Your phone connects through Mtrini Cloud, end-to-end encrypted. Nothing listens on this PC.
            Phones only reach projects you share, and risky steps still ask you.</p>
        </div>
        <input type="checkbox" aria-label="Remote access" checked={st.enabled} disabled={!st.signedIn}
          onChange={(e) => act(() => api.setRemote(e.target.checked), e.target.checked ? 'Remote access on' : 'Remote access off')} />
      </div>
      {!st.signedIn && <p className="hint">Sign in above to turn this on.</p>}
      {st.enabled && (
        <>
          <p className="hint">{st.connected ? `Connected. ${st.phonesOnline.length ? `Online now: ${st.phonesOnline.map((p) => p.name || 'Phone').join(', ')}` : 'No phone online right now.'}` : st.error || 'Connecting…'}</p>
          <label className="f">Shared projects</label>
          {ws && (
            <div className="setrow">
              <span className="mono" style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{ws}</span>
              <button className="btn" onClick={() => act(() => api.shareRemoteProject(ws, !shared), shared ? 'Stopped sharing this project' : 'Project shared with your phone')}>
                {shared ? 'Stop sharing' : 'Share with my phone'}
              </button>
            </div>
          )}
          {st.projects.filter((p) => !ws || p.toLowerCase() !== ws.toLowerCase()).map((p) => (
            <div className="setrow" key={p}>
              <span className="mono" style={{ overflow: 'hidden', textOverflow: 'ellipsis' }}>{p}</span>
              <button className="btn" onClick={() => act(() => api.shareRemoteProject(p, false))}>Stop sharing</button>
            </div>
          ))}
          {st.projects.length === 0 && !ws && <p className="hint">Open a project, then share it here.</p>}
          <label className="f">Paired phones</label>
          {st.paired.length === 0 && <p className="hint">No phone yet. Open Mtrini on your phone, sign in with the same account and pick this PC.</p>}
          {st.paired.map((p) => (
            <div className="setrow" key={p.id}>
              <div><strong>{p.name || 'Phone'}</strong>
                <p className="hint">Paired {new Date(p.pairedAt * 1000).toLocaleDateString()}</p></div>
              <label className="hint" style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                <input type="checkbox" checked={p.allowAuto} onChange={(e) => act(() => api.setRemoteAuto(p.id, e.target.checked))} />
                Allow Auto mode
              </label>
              <button className="btn" onClick={() => act(() => api.forgetRemote(p.id), 'Phone removed')}>Forget</button>
            </div>
          ))}
        </>
      )}
    </div>
  );
}

/** Shown anywhere in the app when a phone asks to pair. */
export function PairingPrompt() {
  const [st, setSt] = useRemote(2500);
  const req = st?.enabled ? st.pending[0] : undefined;
  if (!req) return null;
  const answer = async (yes: boolean) => {
    try { setSt(yes ? await api.approveRemotePair(req.id) : await api.denyRemotePair(req.id)); } catch { /* expired: next poll clears it */ }
  };
  return (
    <div className="modal-back" role="dialog" aria-label="Pair a phone">
      <div className="modal pairing">
        <h3>Pair “{req.name}” with this PC?</h3>
        <p className="hint">Check that your phone shows the same code. If it doesn’t match, deny.</p>
        <div className="paircode mono">{spaced(req.code)}</div>
        <p className="hint">Once paired, this phone can use the projects you share, and asks before any risky step.</p>
        <div className="row" style={{ justifyContent: 'flex-end', gap: 8 }}>
          <button className="btn" onClick={() => answer(false)}>Deny</button>
          <button className="btn primary" onClick={() => answer(true)}>Approve</button>
        </div>
      </div>
    </div>
  );
}
