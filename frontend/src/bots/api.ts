// Client for the Mtrini Bots API (/api/bots). Plain fetch: the app runs on the same machine as its backend.
const BASE = (import.meta as any).env?.VITE_API || '';

export type BotState = { status: 'idle' | 'queued' | 'working' | 'waiting'; label: string; since: number };
export type Bot = {
  id: string; name: string; role: string; instructions: string; provider: string; model: string; effort: string;
  color: string; mascot: string; created: number; paused: boolean; session: number; state: BotState; busy: boolean; folder: string;
  routines: number; unread: number; waiting: number;
};
export type Step = { tool: string; label: string; ok: boolean | null };
export type Message = {
  id: string; role: 'user' | 'assistant'; content: string; ts: number; source?: string; steps?: Step[];
  error?: boolean; stopped?: boolean; approval?: string; routine?: string | boolean;
};
export type InboxItem = {
  id: string; bot: string; botName: string; botColor: string; botMascot?: string; kind: 'briefing' | 'result' | 'message' | 'approval' | 'error';
  title: string; body: string; ts: number; read: boolean; state?: 'pending' | 'approved' | 'denied' | 'expired'; quiet?: boolean;
};
export type Routine = {
  id: string; title: string; prompt: string; kind: 'interval' | 'daily' | 'weekly'; time?: string; minutes?: number;
  days?: number[]; enabled: boolean; when: string; nextRun: number; lastRun?: number | null; lastResult?: string;
};
export type Template = { key: string; name: string; role: string; instructions: string; mascot: string; routines: string[] };
export type Telegram = { connected: boolean; paired: boolean; pairCode: string; defaultBot: string; username: string; running: boolean; error: string };
export type Background = { keepRunning: boolean; autostart: boolean; installed: boolean; desktop: boolean; hasWork: boolean; staysOn: boolean };
export type Provider = { id: string; label?: string; name?: string; configured: boolean; kind?: string; free?: boolean; agentCli?: boolean };
export type BotEvent =
  | { type: 'hello' } | { type: 'bots' }
  | { type: 'state'; bot: string; status: BotState['status']; label: string; since: number }
  | { type: 'message'; bot: string; message: Message }
  | { type: 'live'; bot: string; text: string }
  | { type: 'step'; bot: string; step: Step }
  | { type: 'inbox'; item: InboxItem; botName: string };

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, { ...init, headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) } });
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (body?.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail);
    } catch { /* not JSON */ }
    throw new Error(detail);
  }
  return res.json();
}
const post = <T,>(path: string, body?: unknown) => call<T>(path, { method: 'POST', body: JSON.stringify(body ?? {}) });

export const api = {
  bots: () => call<{ bots: Bot[]; unread: number; browser: boolean; colors: string[] }>('/api/bots'),
  templates: () => call<{ templates: Template[] }>('/api/bots/templates'),
  create: (body: Partial<Bot> & { template?: string }) => post<Bot>('/api/bots', body),
  update: (id: string, patch: Partial<Bot>) => call<Bot>(`/api/bots/${id}`, { method: 'PATCH', body: JSON.stringify(patch) }),
  remove: (id: string) => call<{ ok: boolean }>(`/api/bots/${id}`, { method: 'DELETE' }),
  conversation: (id: string) => call<{ messages: Message[]; state: BotState; busy: boolean }>(`/api/bots/${id}/conversation`),
  send: (id: string, text: string) => post<{ ok: boolean }>(`/api/bots/${id}/message`, { text }),
  stop: (id: string) => post<{ stopped: boolean }>(`/api/bots/${id}/stop`),
  newConversation: (id: string) => post<Bot>(`/api/bots/${id}/new-conversation`),
  memory: (id: string) => call<{ text: string; path: string }>(`/api/bots/${id}/memory`),
  saveMemory: (id: string, text: string) => call<{ ok: boolean }>(`/api/bots/${id}/memory`, { method: 'PUT', body: JSON.stringify({ text }) }),
  routines: (id: string) => call<{ routines: Routine[] }>(`/api/bots/${id}/routines`),
  saveRoutine: (id: string, r: Partial<Routine>) => post<Routine>(`/api/bots/${id}/routines`, r),
  removeRoutine: (id: string, rid: string) => call<{ ok: boolean }>(`/api/bots/${id}/routines/${rid}`, { method: 'DELETE' }),
  runRoutine: (id: string, rid: string) => post<{ ok: boolean }>(`/api/bots/${id}/routines/${rid}/run`),
  files: (id: string) => call<{ files: { path: string; size: number; modified: number }[]; folder: string }>(`/api/bots/${id}/files`),
  file: (id: string, path: string) => call<{ path: string; text: string; binary?: boolean }>(`/api/bots/${id}/file?path=${encodeURIComponent(path)}`),
  showBrowser: (id: string) => post<{ running: boolean; visible: boolean }>(`/api/bots/${id}/browser/show`),
  hideBrowser: (id: string) => post<{ running: boolean; visible: boolean }>(`/api/bots/${id}/browser/hide`),
  inbox: () => call<{ items: InboxItem[]; unread: number }>('/api/bots/inbox'),
  markRead: (bot: string, id: string, read = true) => post<InboxItem>(`/api/bots/inbox/${bot}/${id}/read`, { read }),
  readAll: () => post<{ unread: number }>('/api/bots/inbox/read-all'),
  clearInbox: () => post<{ removed: number }>('/api/bots/inbox/clear'),
  resolve: (bot: string, id: string, decision: 'allow' | 'deny') => post<InboxItem>(`/api/bots/inbox/${bot}/${id}/resolve`, { decision }),
  background: () => call<Background>('/api/bots/background'),
  saveBackground: (patch: Partial<Pick<Background, 'keepRunning' | 'autostart'>>) => post<Background>('/api/bots/background', patch),
  quit: () => post<{ ok: boolean }>('/api/bots/background/quit'),
  telegram: () => call<Telegram>('/api/bots/telegram'),
  telegramConnect: (token: string) => post<Telegram>('/api/bots/telegram', { token }),
  telegramDefault: (defaultBot: string) => post<Telegram>('/api/bots/telegram', { defaultBot }),
  telegramDisconnect: () => call<Telegram>('/api/bots/telegram', { method: 'DELETE' }),
  providers: () => call<{ providers: Provider[] }>('/api/providers'),
  models: (provider: string) => call<{ models: { id: string; label: string }[] }>(`/api/models?provider=${encodeURIComponent(provider)}`),
};

// Live updates. Returns a function that closes the stream.
export function listen(onEvent: (ev: BotEvent) => void, onDrop?: () => void): () => void {
  if (typeof EventSource === 'undefined') return () => {};
  const es = new EventSource(BASE + '/api/bots/events');
  es.onmessage = (m) => {
    try { onEvent(JSON.parse(m.data)); } catch { /* a keep-alive or a broken line */ }
  };
  es.onerror = () => onDrop?.();
  return () => es.close();
}

export function ago(ts: number, now = Date.now() / 1000): string {
  const s = Math.max(0, now - ts);
  if (s < 60) return 'now';
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return new Date(ts * 1000).toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
}

export function until(ts: number, now = Date.now() / 1000): string {
  const s = ts - now;
  if (s <= 60) return 'in a moment';
  if (s < 3600) return `in ${Math.round(s / 60)} min`;
  if (s < 86400) return `in ${Math.round(s / 3600)} h`;
  return new Date(ts * 1000).toLocaleString(undefined, { weekday: 'short', hour: '2-digit', minute: '2-digit' });
}
