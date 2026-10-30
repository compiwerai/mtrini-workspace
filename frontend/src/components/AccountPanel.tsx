import React, { useEffect, useRef, useState } from 'react';
import { api } from '../api/client';

const LABEL: Record<string, string> = { google: 'Google', discord: 'Discord', github: 'GitHub' };
const label = (p: string) => LABEL[p] || p;

/** Settings → Account: optional Mtrini account (needed for the phone app and sync). */
export default function AccountPanel({ onToast }: { onToast: (s: string) => void }) {
  const [acc, setAcc] = useState<any>(null);
  const [waiting, setWaiting] = useState<{ loginId: string; url: string; link: boolean } | null>(null);
  const timer = useRef<number | null>(null);

  const load = () => api.account().then(setAcc).catch((e: any) => setAcc({ error: String(e.message || e) }));
  useEffect(() => { load(); return () => { if (timer.current) window.clearInterval(timer.current); }; }, []);

  const stopWaiting = (loginId?: string) => {
    if (timer.current) window.clearInterval(timer.current);
    timer.current = null;
    if (loginId) api.cancelAccountLogin(loginId).catch(() => {});
    setWaiting(null);
  };

  const start = async (provider: string, link = false) => {
    try {
      const s = await api.accountLogin(provider, link);
      setWaiting({ loginId: s.loginId, url: s.url, link });
      const began = Date.now();
      timer.current = window.setInterval(async () => {
        if (Date.now() - began > 10 * 60 * 1000) { stopWaiting(s.loginId); onToast('Sign-in timed out. Try again.'); return; }
        try {
          const r = await api.pollAccountLogin(s.loginId);
          if (r.status === 'pending') return;
          stopWaiting();
          if (r.status === 'done') onToast(`Signed in${r.user?.name ? ` as ${r.user.name}` : ''}`);
          else if (r.status === 'linked') onToast(`${label(r.provider)} linked to your account`);
          else onToast(r.message || 'Sign-in didn’t finish. Try again.');
          load();
        } catch { /* keep waiting; the network may blip */ }
      }, (s.interval || 2) * 1000);
    } catch (e: any) { onToast(`Couldn’t start sign-in: ${e.message || e}`); }
  };

  const act = async (fn: () => Promise<any>, done: string) => {
    try { await fn(); onToast(done); load(); } catch (e: any) {
      const raw = String(e.message || e);
      onToast(/"detail"\s*:\s*"([^"]+)"/.exec(raw)?.[1] || raw);
    }
  };

  if (!acc) return <p className="hint">Loading…</p>;
  if (acc.error) return <p className="hint">Couldn’t load your account: {acc.error}</p>;
  if (!acc.configured) {
    return (
      <div className="account">
        <h3>Mtrini account</h3>
        <p className="hint">Accounts are coming soon. They’ll let you use Mtrini Workspace from your phone and keep your sessions in sync. Everything else works without one.</p>
      </div>
    );
  }
  if (acc.reachable === false) {
    return <div className="account"><h3>Mtrini account</h3><p className="hint">Can’t reach Mtrini Cloud right now. Check your connection and try again.</p>
      <button className="btn" onClick={load}>Try again</button></div>;
  }

  if (waiting) {
    return (
      <div className="account">
        <h3>{waiting.link ? 'Linking another sign-in' : 'Finish signing in in your browser'}</h3>
        <p className="hint">A browser tab opened for you. Sign in there, then come back here; this page updates by itself.</p>
        <div className="row">
          <a className="btn" href={waiting.url} target="_blank" rel="noreferrer">Open the link again</a>
          <button className="btn" onClick={() => stopWaiting(waiting.loginId)}>Cancel</button>
        </div>
      </div>
    );
  }

  const providers: string[] = acc.providers || [];
  if (!acc.signedIn) {
    return (
      <div className="account">
        <h3>Sign in to Mtrini</h3>
        <p className="hint">Optional. An account lets you use Mtrini Workspace from your phone and keep your sessions in sync. Mtrini only receives your name, email and picture.</p>
        <div className="signins">
          {providers.map((p) => <button key={p} className="btn" onClick={() => start(p)}>Continue with {label(p)}</button>)}
          {providers.length === 0 && <p className="hint">No sign-in options are available yet.</p>}
        </div>
      </div>
    );
  }

  const linked: string[] = (acc.identities || []).map((i: any) => i.provider);
  return (
    <div className="account">
      <div className="who">
        {acc.user?.avatar ? <img src={acc.user.avatar} alt="" width={44} height={44} /> : <span className="avatar">{(acc.user?.name || '?')[0]}</span>}
        <div><strong>{acc.user?.name || 'Your account'}</strong><div className="hint">{acc.user?.email}</div></div>
      </div>

      <div className="label-caps">Sign-ins</div>
      {(acc.identities || []).map((i: any) => (
        <div key={i.provider} className="setrow">
          <span>{label(i.provider)} <span className="hint">{i.email || i.username}</span></span>
          {linked.length > 1 && <button className="btn" onClick={() => act(() => api.unlinkAccount(i.provider), `${label(i.provider)} unlinked`)}>Unlink</button>}
        </div>
      ))}
      <div className="row" style={{ marginTop: 8 }}>
        {providers.filter((p) => !linked.includes(p)).map((p) => (
          <button key={p} className="btn" onClick={() => start(p, true)}>Link {label(p)}</button>
        ))}
      </div>

      <div className="label-caps" style={{ marginTop: 18 }}>Devices</div>
      {(acc.devices || []).map((d: any) => (
        <div key={d.id} className="setrow">
          <span>{d.name || 'Device'} {d.current && <span className="tag">This device</span>}</span>
          {!d.current && <button className="btn" onClick={() => act(() => api.revokeAccountDevice(d.id), 'Device signed out')}>Sign out</button>}
        </div>
      ))}

      <div className="row" style={{ marginTop: 18 }}>
        <button className="btn" onClick={() => act(() => api.accountLogout(), 'Signed out')}>Sign out</button>
        <button className="btn danger" onClick={() => {
          if (confirm('Delete your Mtrini account? This removes your sign-ins and devices from Mtrini Cloud. Your projects and local sessions stay on this computer.')) {
            act(() => api.deleteAccount(), 'Account deleted');
          }
        }}>Delete account</button>
      </div>
    </div>
  );
}
