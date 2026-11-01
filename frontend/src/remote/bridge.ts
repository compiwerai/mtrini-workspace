/**
 * The phone side of remote access: connects to Mtrini Cloud's bridge, pairs with a PC (6-digit code check),
 * and carries API requests to it end-to-end encrypted. `transport(pcId)` plugs into api/client.ts, so every
 * screen of the app works over the bridge without changes. Protocol: cloud/src/bridge.js and backend/mtrini/remote.py.
 */
import { b64u, newKeyPair, Opener, pairingCode, seal, sharedKey, unb64u, type KeyPair } from './crypto';

export type PC = { id: string; name: string; pub: string };
type Paired = { id: string; name: string; pub: string };
type Pending = {
  resolve: (r: Response) => void;
  reject: (e: Error) => void;
  stream?: ReadableStreamDefaultController<Uint8Array>;
  timer?: number;
};

const KEY_STORE = 'mtrini.phone.key';
const PAIRED_STORE = 'mtrini.phone.paired';
const te = new TextEncoder();

function loadJson<T>(k: string, fallback: T): T {
  try { return JSON.parse(localStorage.getItem(k) || '') as T; } catch { return fallback; }
}

export class PhoneBridge {
  ws: WebSocket | null = null;
  pcs: PC[] = [];
  me: string;
  private key: KeyPair | null = null;
  private keys = new Map<string, CryptoKey>();
  private openers = new Map<string, Opener>();
  private pending = new Map<number, Pending>();
  private pairWaiters = new Map<string, { ok: () => void; no: (e: Error) => void }>();
  private rid = 0;
  private listeners = new Set<() => void>();
  status: 'connecting' | 'online' | 'offline' = 'connecting';

  constructor(private cloud: string, private token: string, deviceId: string, private name = 'Phone') {
    this.me = deviceId;
  }

  onChange(fn: () => void) { this.listeners.add(fn); return () => this.listeners.delete(fn); }
  private emit() { this.listeners.forEach((f) => f()); }

  paired(): Record<string, Paired> { return loadJson(PAIRED_STORE, {}); }
  isPaired(pcId: string) { return Boolean(this.paired()[pcId]); }

  private async myKey(): Promise<KeyPair> {
    if (this.key) return this.key;
    const saved = loadJson<KeyPair | null>(KEY_STORE, null);
    this.key = saved || (await newKeyPair());
    if (!saved) localStorage.setItem(KEY_STORE, JSON.stringify(this.key));
    return this.key;
  }

  connect() {
    const url = this.cloud.replace(/^http/, 'ws') + '/bridge';
    const ws = new WebSocket(url, ['mtrini.v1', `bearer.${this.token}`]);
    this.ws = ws;
    this.status = 'connecting';
    ws.onopen = () => { ws.send(JSON.stringify({ t: 'hello', role: 'phone', name: this.name })); this.status = 'online'; this.emit(); };
    ws.onclose = () => {
      this.status = 'offline';
      for (const p of this.pending.values()) { p.stream ? p.stream.error(new Error('Connection lost')) : p.reject(new Error('Connection lost')); }
      this.pending.clear();
      this.emit();
      if (this.ws === ws) window.setTimeout(() => this.connect(), 3000);
    };
    ws.onmessage = (ev) => { this.onFrame(String(ev.data)).catch(() => {}); };
  }

  close() { const ws = this.ws; this.ws = null; ws?.close(); }

  private send(obj: object) { this.ws?.send(JSON.stringify(obj)); }

  private async keyFor(pcId: string): Promise<CryptoKey> {
    let k = this.keys.get(pcId);
    if (!k) {
      const pc = this.paired()[pcId] || this.pcs.find((p) => p.id === pcId);
      if (!pc) throw new Error('Unknown PC');
      const me = await this.myKey();
      k = await sharedKey(me, pc.pub, pc.pub, me.pub);
      this.keys.set(pcId, k);
    }
    return k;
  }

  private async onFrame(text: string) {
    const msg = JSON.parse(text);
    if (msg.t === 'presence') { this.pcs = msg.pcs || []; this.emit(); return; }
    if (msg.t !== 'from' || msg.role !== 'pc') return;
    const pcId: string = msg.from, data = msg.data;
    if (data && data.kind === 'pair-no') { this.pairWaiters.get(pcId)?.no(new Error('The PC denied pairing.')); return; }
    if (data && data.kind === 'unpaired') {
      const all = this.paired(); delete all[pcId]; localStorage.setItem(PAIRED_STORE, JSON.stringify(all));
      this.keys.delete(pcId); this.openers.delete(pcId); this.emit();
      return;
    }
    let op = this.openers.get(pcId);
    if (!op) { op = new Opener(await this.keyFor(pcId), pcId, this.me); this.openers.set(pcId, op); }
    let body: any;
    try { body = await op.open(data); } catch { return; }
    if (body.kind === 'pair-ok') { this.pairWaiters.get(pcId)?.ok(); return; }
    const p = this.pending.get(body.rid);
    if (!p) return;
    if (body.kind === 'res') {
      window.clearTimeout(p.timer);
      this.pending.delete(body.rid);
      const content = body.b64 ? unb64u(body.b64) : body.body || '';
      p.resolve(new Response(content, { status: body.status, headers: { 'content-type': body.type || 'application/json' } }));
    } else if (body.kind === 'head') {
      window.clearTimeout(p.timer);
      const stream = new ReadableStream<Uint8Array>({ start: (c) => { p.stream = c; } });
      p.resolve(new Response(stream, { status: body.status, headers: { 'content-type': body.type } }));
    } else if (body.kind === 'chunk') {
      p.stream?.enqueue(te.encode(body.data));
    } else if (body.kind === 'end') {
      p.stream?.close();
      this.pending.delete(body.rid);
    }
  }

  /** Starts pairing: returns the 6-digit code to compare, and a promise that settles when the PC answers. */
  async pair(pc: PC): Promise<{ code: string; done: Promise<void> }> {
    const me = await this.myKey();
    const code = await pairingCode(pc.pub, me.pub);
    this.keys.delete(pc.id); this.openers.delete(pc.id);
    const done = new Promise<void>((ok, no) => {
      this.pairWaiters.set(pc.id, {
        ok: () => {
          const all = this.paired(); all[pc.id] = { id: pc.id, name: pc.name, pub: pc.pub };
          localStorage.setItem(PAIRED_STORE, JSON.stringify(all));
          this.pairWaiters.delete(pc.id); ok(); this.emit();
        },
        no: (e) => { this.pairWaiters.delete(pc.id); no(e); },
      });
    });
    // the PC answers pair-ok encrypted with the key we'd share; prepare to read it
    this.keys.set(pc.id, await sharedKey(me, pc.pub, pc.pub, me.pub));
    this.send({ t: 'to', to: pc.id, data: { kind: 'pair-req', pub: me.pub, name: this.name } });
    return { code, done };
  }

  /** Seal something for one PC with this phone's pairing key: used for work queued in the cloud (remote/cloud.ts). */
  async sealFor(pcId: string, payload: object) {
    return seal(await this.keyFor(pcId), this.me, pcId, payload);
  }

  forget(pcId: string) {
    const all = this.paired(); delete all[pcId]; localStorage.setItem(PAIRED_STORE, JSON.stringify(all));
    this.keys.delete(pcId); this.openers.delete(pcId); this.emit();
  }

  /** A fetch-like function that sends /api requests to this PC through the bridge. */
  transport(pcId: string) {
    return async (url: string, init: RequestInit = {}): Promise<Response> => {
      const u = new URL(url, 'http://pc');
      let body: any;
      if (init.body) { try { body = JSON.parse(String(init.body)); } catch { body = undefined; } }
      const rid = ++this.rid;
      const payload = { kind: 'req', rid, method: (init.method || 'GET').toUpperCase(), url: u.pathname + u.search, body };
      const box = await seal(await this.keyFor(pcId), this.me, pcId, payload);
      return new Promise<Response>((resolve, reject) => {
        const p: Pending = { resolve, reject };
        p.timer = window.setTimeout(() => { this.pending.delete(rid); reject(new Error('The PC did not answer.')); }, 30000);
        this.pending.set(rid, p);
        init.signal?.addEventListener('abort', () => { this.pending.delete(rid); p.stream?.close(); reject(new DOMException('Aborted', 'AbortError')); });
        this.send({ t: 'to', to: pcId, data: box });
      });
    };
  }
}

export { b64u };
