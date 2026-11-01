import React, { useEffect, useMemo, useRef, useState } from 'react';
import App from '../App';
import { setTransport, setWorkspace } from '../api/client';
import { PhoneBridge, type PC } from '../remote/bridge';

/**
 * The Android app: sign in to Mtrini Cloud, pick your PC, pair once (compare a 6-digit code, approve on the PC),
 * pick a shared project, then use the normal app, with every request going to the PC through the encrypted bridge.
 */
const CLOUD = ((import.meta as any).env?.VITE_CLOUD || 'https://mtrini-cloud.roblox-event-bot-worker.workers.dev').replace(/\/+$/, '');
const SESSION = 'mtrini.phone.session';
type Session = { token: string; deviceId: string; name: string };
type Project = { path: string; name: string };

const loadSession = (): Session | null => { try { return JSON.parse(localStorage.getItem(SESSION) || ''); } catch { return null; } };
const spaced = (c: string) => `${c.slice(0, 3)} ${c.slice(3)}`;

async function openExternal(url: string) {
  try {
    const mod: any = await import(/* @vite-ignore */ '@capacitor/browser');
    await mod.Browser.open({ url });
  } catch {
    window.open(url, '_blank');
  }
}

function SignIn({ onDone }: { onDone: (s: Session) => void }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');
  const timer = useRef<number>();
  useEffect(() => () => window.clearInterval(timer.current), []);
  const start = async (provider: string) => {
    setBusy(true); setErr('');
    try {
      const name = /android/i.test(navigator.userAgent) ? 'Android phone' : 'Phone';
      const r = await fetch(`${CLOUD}/auth/device`, { method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ device_name: name, platform: 'android', provider }) });
      const s = await r.json();
      if (!r.ok) throw new Error(s?.error?.message || 'Could not start sign-in.');
      await openExternal(s.url);
      timer.current = window.setInterval(async () => {
        const p = await fetch(`${CLOUD}/auth/device/poll`, { method: 'POST', headers: { 'content-type': 'application/json' },
          body: JSON.stringify({ login_id: s.login_id, poll_secret: s.poll_secret }) }).then((x) => x.json()).catch(() => null);
        if (!p || p.status === 'pending') return;
        window.clearInterval(timer.current);
        if (p.status === 'done') {
          const sess = { token: p.session_token, deviceId: p.device_id, name };
          localStorage.setItem(SESSION, JSON.stringify(sess));
          onDone(sess);
        } else { setBusy(false); setErr(p.message || 'Sign-in did not finish. Try again.'); }
      }, 2000);
    } catch (e: any) { setBusy(false); setErr(String(e.message || e)); }
  };
  return (
    <div className="phone-screen">
      <img className="phone-logo" src="/logo.svg" alt="" onError={(e) => ((e.target as HTMLImageElement).style.display = 'none')} />
      <h1>Mtrini Workspace</h1>
      <p className="hint">Use your PC’s coding agent from your phone. Sign in with the same account as on your PC.</p>
      <button className="btn primary wide" disabled={busy} onClick={() => start('discord')}>Continue with Discord</button>
      <button className="btn wide" disabled={busy} onClick={() => start('github')}>Continue with GitHub</button>
      {busy && <p className="hint">Finish signing in in your browser, then come back here.</p>}
      {err && <p className="notice" role="alert">{err}</p>}
    </div>
  );
}

export default function PhoneShell() {
  const [session, setSession] = useState<Session | null>(loadSession);
  const [, tick] = useState(0);
  const [pc, setPc] = useState<PC | null>(null);
  const [pairing, setPairing] = useState<{ pc: PC; code: string; error?: string } | null>(null);
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [ready, setReady] = useState<{ pc: PC; project: Project } | null>(null);
  const [menu, setMenu] = useState(false);

  const bridge = useMemo(() => (session ? new PhoneBridge(CLOUD, session.token, session.deviceId, session.name) : null), [session]);
  useEffect(() => {
    document.documentElement.classList.add('phone');
    if (!bridge) return;
    const off = bridge.onChange(() => tick((n) => n + 1));
    bridge.connect();
    return () => { off(); bridge.close(); };
  }, [bridge]);
  useEffect(() => { document.documentElement.classList.toggle('side-open', menu); }, [menu]);

  // once a paired PC is picked, ask it which projects it shares
  useEffect(() => {
    if (!bridge || !pc || !bridge.isPaired(pc.id)) return;
    setProjects(null);
    bridge.transport(pc.id)('/api/remote/shared').then((r) => r.json()).then((d) => setProjects(d.projects || []))
      .catch(() => setProjects([]));
  }, [bridge, pc, pairing]);

  if (!session || !bridge) return <SignIn onDone={setSession} />;

  if (ready) {
    const online = bridge.pcs.some((p) => p.id === ready.pc.id);
    return (
      <div className="phone-app">
        <header className="phone-bar">
          <button className="btn iconbtn" aria-label="Menu" onClick={() => setMenu((v) => !v)}>☰</button>
          <span className="phone-title">{ready.project.name} <span className="hint">on {ready.pc.name}</span></span>
          <button className="btn" onClick={() => { setTransport(null); setReady(null); }}>Switch</button>
        </header>
        {!online && <div className="notice">Your PC is offline. Requests will work again when it reconnects.</div>}
        {menu && <div className="phone-scrim" onClick={() => setMenu(false)} />}
        <App />
      </div>
    );
  }

  const signOut = () => { bridge.close(); localStorage.removeItem(SESSION); setSession(null); };

  if (pairing) {
    return (
      <div className="phone-screen">
        <h1>Pair with {pairing.pc.name}</h1>
        <p className="hint">Check that your PC shows this same code, then press Approve on the PC.</p>
        <div className="paircode mono">{spaced(pairing.code)}</div>
        {pairing.error ? <p className="notice" role="alert">{pairing.error}</p> : <p className="hint">Waiting for your PC…</p>}
        <button className="btn wide" onClick={() => setPairing(null)}>Back</button>
      </div>
    );
  }

  if (pc && bridge.isPaired(pc.id)) {
    return (
      <div className="phone-screen">
        <h1>Pick a project</h1>
        <p className="hint">These are the projects shared from {pc.name}. Share more in Settings → Account → Remote access on your PC.</p>
        {projects === null && <p className="hint">Loading…</p>}
        {projects?.length === 0 && <p className="hint">Nothing is shared yet. On your PC, open a project and choose “Share with my phone”.</p>}
        {projects?.map((p) => (
          <button key={p.path} className="btn wide listbtn" onClick={() => {
            setTransport(bridge.transport(pc.id)); setWorkspace(p.path); setReady({ pc, project: p });
          }}><strong>{p.name}</strong><span className="hint">{p.path}</span></button>
        ))}
        <button className="btn wide" onClick={() => setPc(null)}>Back</button>
      </div>
    );
  }

  return (
    <div className="phone-screen">
      <h1>Your PCs</h1>
      <p className="hint">{bridge.status === 'online' ? 'PCs with Remote access turned on show up here.' : 'Connecting to Mtrini Cloud…'}</p>
      {bridge.pcs.length === 0 && bridge.status === 'online' && (
        <p className="hint">No PC online. On your PC: Settings → Account → turn on Remote access.</p>
      )}
      {bridge.pcs.map((p) => (
        <button key={p.id} className="btn wide listbtn" onClick={async () => {
          setPc(p);
          if (bridge.isPaired(p.id)) return;
          const { code, done } = await bridge.pair(p);
          setPairing({ pc: p, code });
          done.then(() => setPairing(null)).catch((e) => setPairing({ pc: p, code, error: String(e.message || e) }));
        }}><strong>{p.name}</strong><span className="hint">{bridge.isPaired(p.id) ? 'Paired' : 'Tap to pair'}</span></button>
      ))}
      <button className="btn wide" onClick={signOut}>Sign out</button>
    </div>
  );
}
