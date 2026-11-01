/**
 * End-to-end encryption for the phone-to-PC bridge (Web Crypto). Same scheme as
 * backend/mtrini/remote_crypto.py; see that file for the spec. Tests check both sides agree.
 */
const enc = new TextEncoder();
const dec = new TextDecoder();
export const MAX_AGE = 120; // seconds
type Bytes = Uint8Array<ArrayBuffer>;

export const b64u = (b: Uint8Array): string =>
  btoa(String.fromCharCode(...b)).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
export const unb64u = (s: string): Bytes =>
  Uint8Array.from(atob(s.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (s.length % 4)) % 4)), (c) => c.charCodeAt(0));
const cat = (...parts: Uint8Array[]): Bytes => {
  const out = new Uint8Array(parts.reduce((n, p) => n + p.length, 0));
  let o = 0;
  for (const p of parts) { out.set(p, o); o += p.length; }
  return out;
};
const sha256 = async (b: Bytes): Promise<Bytes> => new Uint8Array(await crypto.subtle.digest('SHA-256', b));

export type KeyPair = { privateJwk: JsonWebKey; pub: string };

export async function newKeyPair(): Promise<KeyPair> {
  const kp = await crypto.subtle.generateKey({ name: 'ECDH', namedCurve: 'P-256' }, true, ['deriveBits']);
  const raw = new Uint8Array(await crypto.subtle.exportKey('raw', kp.publicKey));
  return { privateJwk: await crypto.subtle.exportKey('jwk', kp.privateKey), pub: b64u(raw) };
}

export async function pairingCode(pcPub: string, phonePub: string): Promise<string> {
  const d = await sha256(cat(enc.encode('mtrini-pair-v1'), unb64u(pcPub), unb64u(phonePub)));
  const n = ((d[0] << 24) >>> 0) + (d[1] << 16) + (d[2] << 8) + d[3];
  return String(n % 1_000_000).padStart(6, '0');
}

export async function sharedKey(own: KeyPair, peerPub: string, pcPub: string, phonePub: string): Promise<CryptoKey> {
  const priv = await crypto.subtle.importKey('jwk', own.privateJwk, { name: 'ECDH', namedCurve: 'P-256' }, false, ['deriveBits']);
  const peer = await crypto.subtle.importKey('raw', unb64u(peerPub), { name: 'ECDH', namedCurve: 'P-256' }, false, []);
  const secret = await crypto.subtle.deriveBits({ name: 'ECDH', public: peer }, priv, 256);
  const hk = await crypto.subtle.importKey('raw', secret, 'HKDF', false, ['deriveKey']);
  const salt = await sha256(cat(unb64u(pcPub), unb64u(phonePub)));
  return crypto.subtle.deriveKey({ name: 'HKDF', hash: 'SHA-256', salt, info: enc.encode('mtrini-bridge-v1') },
    hk, { name: 'AES-GCM', length: 256 }, false, ['encrypt', 'decrypt']);
}

export type Box = { v: 1; iv: string; c: string };

export async function seal(key: CryptoKey, sender: string, receiver: string, payload: object): Promise<Box> {
  const body = { ...payload, ts: Date.now(), id: b64u(crypto.getRandomValues(new Uint8Array(12))) };
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const c = new Uint8Array(await crypto.subtle.encrypt({ name: 'AES-GCM', iv, additionalData: enc.encode(`${sender}>${receiver}`) },
    key, enc.encode(JSON.stringify(body))));
  return { v: 1, iv: b64u(iv), c: b64u(c) };
}

/** Decrypts messages from one peer and refuses old or repeated ones. */
export class Opener {
  private seen = new Map<string, number>();
  constructor(private key: CryptoKey, private sender: string, private receiver: string) {}

  async open(box: Box): Promise<any> {
    if (!box || box.v !== 1) throw new Error('unknown message format');
    const plain = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: unb64u(box.iv), additionalData: enc.encode(`${this.sender}>${this.receiver}`) },
      this.key, unb64u(box.c));
    const body = JSON.parse(dec.decode(plain));
    const now = Date.now() / 1000;
    if (Math.abs(now - (body.ts || 0) / 1000) > MAX_AGE) throw new Error('message too old');
    if (!body.id || this.seen.has(body.id)) throw new Error('replayed message');
    for (const [k, t] of this.seen) if (now - t > MAX_AGE * 2) this.seen.delete(k);
    this.seen.set(body.id, now);
    return body;
  }
}
