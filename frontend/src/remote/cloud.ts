/**
 * The phone's side of Mtrini Cloud: sessions saved by your PCs (cloud/src/sync.js), kept here too so they open
 * without a connection; work queued for a PC, sealed with the pairing key so only that PC can run it; and the
 * free model, so the phone can chat when no PC is around.
 */
import type { PhoneBridge } from './bridge';

export type CloudThreadMeta = { id: string; pc: string; workspace: string; title: string; preview: string; messages: number;
  created: number; updated: number; rev: number; deleted: boolean };
export type CloudMsg = { role: string; content?: string; ts?: number; tool?: string; ok?: boolean; args?: any; [k: string]: any };
export type CloudThread = { id: string; title: string; created: number; updated: number; workspace?: string; messages: CloudMsg[] };
export type Task = { id: string; device_id: string; thread_id: string; workspace: string; status: string; error: string; created: number;
  prompt: string; local?: string };

const FREE_RELAY = 'https://mtrini-free.roblox-event-bot-worker.workers.dev';
const LIST = 'mtrini.phone.cache.list';
const ONE = 'mtrini.phone.cache.t.';
const SENT = 'mtrini.phone.sent'; // what this phone queued, readable here (the cloud only has the sealed copy)

function cached<T>(k: string, fallback: T): T {
  try { return JSON.parse(localStorage.getItem(k) || '') as T; } catch { return fallback; }
}
function keep(k: string, v: unknown) {
  try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* storage full: the cache is only a convenience */ }
}

export function installId(): string {
  let v = localStorage.getItem('mtrini.phone.install') || '';
  if (!/^[0-9a-f]{32}$/.test(v)) {
    v = [...crypto.getRandomValues(new Uint8Array(16))].map((b) => b.toString(16).padStart(2, '0')).join('');
    localStorage.setItem('mtrini.phone.install', v);
  }
  return v;
}

export class Cloud {
  constructor(private base: string, private token: string) {}

  async call(path: string, init: RequestInit = {}): Promise<Response> {
    return fetch(this.base + path, { ...init, headers: { 'content-type': 'application/json', authorization: `Bearer ${this.token}`, ...(init.headers || {}) } });
  }

  private async json(path: string, init?: RequestInit) {
    const r = await this.call(path, init);
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw Object.assign(new Error(d?.error?.message || `Mtrini Cloud answered ${r.status}.`), { status: r.status, data: d });
    return d;
  }

  me() { return this.json('/me'); }

  /** Every session in the account, newest first; works offline from the last copy. */
  cachedThreads(): CloudThreadMeta[] { return cached<{ rev: number; threads: CloudThreadMeta[] }>(LIST, { rev: 0, threads: [] }).threads; }

  async threads(): Promise<CloudThreadMeta[]> {
    const c = cached<{ rev: number; threads: CloudThreadMeta[] }>(LIST, { rev: 0, threads: [] });
    let { rev } = c;
    const byId = new Map(c.threads.map((t) => [t.id, t]));
    for (let i = 0; i < 20; i++) {
      const d = await this.json(`/sync/threads?since=${rev}`);
      for (const t of d.threads as CloudThreadMeta[]) {
        if (t.deleted) { byId.delete(t.id); localStorage.removeItem(ONE + t.id); } else byId.set(t.id, t);
      }
      rev = d.rev;
      if (!d.more) break;
    }
    const threads = [...byId.values()].sort((a, b) => b.updated - a.updated);
    keep(LIST, { rev, threads });
    return threads;
  }

  cachedThread(id: string): (CloudThread & { rev?: number }) | null { return cached(ONE + id, null); }

  async thread(id: string): Promise<CloudThread & { rev: number }> {
    const d = await this.json(`/sync/threads/${id}`);
    const t = { ...d.thread, rev: d.rev };
    keep(ONE + id, t);
    return t;
  }

  /** Save a session that lives on the phone (a free-model chat); retries on top of a newer copy. */
  async save(t: CloudThread & { rev?: number }): Promise<number> {
    const { rev, ...thread } = t;
    const r = await this.call(`/sync/threads/${t.id}`, { method: 'PUT', body: JSON.stringify({ thread, ...(rev ? { base_rev: rev } : {}) }) });
    const d = await r.json().catch(() => ({}));
    if (r.status === 409) {
      const seen = new Set(d.thread.messages.map((m: CloudMsg) => `${m.role}|${m.ts}|${m.content}`));
      const merged = { ...t, rev: d.rev, messages: [...d.thread.messages, ...t.messages.filter((m) => !seen.has(`${m.role}|${m.ts}|${m.content}`))] };
      return this.save(merged);
    }
    if (!r.ok) throw new Error(d?.error?.message || `Mtrini Cloud answered ${r.status}.`);
    keep(ONE + t.id, { ...t, rev: d.rev });
    return d.rev;
  }

  async remove(id: string) {
    await this.json(`/sync/threads/${id}`, { method: 'DELETE' });
    localStorage.removeItem(ONE + id);
    const c = cached<{ rev: number; threads: CloudThreadMeta[] }>(LIST, { rev: 0, threads: [] });
    keep(LIST, { ...c, threads: c.threads.filter((t) => t.id !== id) });
  }

  /** Queue work for a PC. It's sealed for that PC, so the cloud can't read or change it. */
  async queue(bridge: PhoneBridge, pc: string, threadId: string, workspace: string, prompt: string, mode: string,
    model?: { provider: string; model: string }): Promise<Task> {
    const id = crypto.randomUUID();
    const box = await bridge.sealFor(pc, { kind: 'task', task: id, thread_id: threadId, workspace, prompt, mode,
      provider: model?.provider || '', model: model?.model || '' });
    const d = await this.json('/sync/tasks', { method: 'POST', body: JSON.stringify({ pc, thread_id: threadId, workspace, prompt: JSON.stringify(box), mode }) });
    const sent = cached<Record<string, string>>(SENT, {});
    sent[d.task.id] = prompt;
    keep(SENT, sent);
    return { ...d.task, local: prompt };
  }

  async tasks(): Promise<Task[]> {
    const sent = cached<Record<string, string>>(SENT, {});
    return ((await this.json('/sync/tasks')).tasks as Task[]).map((t) => ({ ...t, local: sent[t.id] }));
  }

  cancel(id: string) { return this.json(`/sync/tasks/${id}`, { method: 'DELETE' }); }
}

/** One answer from the built-in free model, streamed. */
export async function freeChat(messages: { role: string; content: string }[], onText: (text: string) => void, signal?: AbortSignal) {
  const r = await fetch(`${FREE_RELAY}/v1/chat/completions`, {
    method: 'POST', signal,
    headers: { 'content-type': 'application/json', 'x-mtrini-install': installId() },
    body: JSON.stringify({ messages, stream: true }),
  });
  if (!r.ok || !r.body) {
    const d = await r.json().catch(() => ({}));
    throw new Error(d?.error?.message || `The free model answered ${r.status}.`);
  }
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = '', text = '';
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    const lines = buf.split('\n');
    buf = lines.pop() || '';
    for (const line of lines) {
      if (!line.startsWith('data: ') || line === 'data: [DONE]') continue;
      try {
        const delta = JSON.parse(line.slice(6)).choices?.[0]?.delta?.content;
        if (delta) { text += delta; onText(text); }
      } catch { /* a partial line */ }
    }
  }
  return text;
}
