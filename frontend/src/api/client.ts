export type SkillScope = 'project' | 'global';
export type Skill = { name: string; scope: SkillScope; description: string; summary?: string };

const BASE = (import.meta as any).env?.VITE_API || '';

// How requests reach the backend: plain fetch on the PC; the encrypted bridge on the phone (see remote/bridge.ts).
type Transport = (url: string, init: RequestInit) => Promise<Response>;
let transport: Transport = (url, init) => fetch(url, init);
export function setTransport(t: Transport | null) {
  transport = t || ((url, init) => fetch(url, init));
}

let WS: string | null = localStorage.getItem('mtrini.workspace');
let OV: string | null = null; // per-thread execution override (thread folder beats global)
export function setExecOverride(p: string | null) {
  OV = p;
}
export function setWorkspace(p: string | null) {
  WS = p;
  if (p) localStorage.setItem('mtrini.workspace', p);
  else localStorage.removeItem('mtrini.workspace');
}
export function getWorkspace() {
  return WS;
}
function recents(): string[] {
  try { return JSON.parse(localStorage.getItem('mtrini.recent') || '[]'); } catch { return []; }
}
export function touchRecent(p: string) {
  const r = [p, ...recents().filter((x) => x !== p)].slice(0, 8);
  localStorage.setItem('mtrini.recent', JSON.stringify(r));
}
export function getRecents() {
  return recents();
}

function inject(url: string, init?: RequestInit, pin?: boolean): { url: string; init?: RequestInit } {
  const target = pin ? WS : OV || WS;
  if (!target || !url.startsWith('/api')) return { url, init };
  const method = (init?.method || 'GET').toUpperCase();
  if (method === 'GET' || method === 'DELETE' || !init?.body) {
    if (/[?&]workspace=/.test(url)) return { url, init };
    return { url: `${url}${url.includes('?') ? '&' : '?'}workspace=${encodeURIComponent(target)}`, init };
  }
  try {
    const body = JSON.parse(String((init as any).body));
    if (body && typeof body === 'object' && !Array.isArray(body) && !('workspace' in body)) {
      return { url, init: { ...init, body: JSON.stringify({ ...body, workspace: target }) } };
    }
  } catch { /* not JSON */ }
  return { url, init };
}

/** A request to the backend with no workspace added and no error thrown: for callers that read error bodies. */
export function rawRequest(url: string, init: RequestInit = {}) {
  return transport(BASE + url, { ...init, headers: { 'content-type': 'application/json', ...(init.headers || {}) } });
}

async function j<T>(url: string, init?: RequestInit, opts?: { pin?: boolean }): Promise<T> {
  const w = inject(url, init, opts?.pin);
  const r = await transport(BASE + w.url, { ...w.init, headers: { 'content-type': 'application/json', ...(w.init?.headers || {}) } });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json() as Promise<T>;
}

export const api = {
  health: () => j('/api/health'),
  about: () => j<any>('/api/about'),
  runtimes: () => j<any>('/api/runtimes'),
  providers: () => j<any>('/api/providers'),
  configureProvider: (b: any) => j('/api/providers/configure', { method: 'POST', body: JSON.stringify(b) }),
  disconnect: (provider: string) => j('/api/providers/disconnect', { method: 'POST', body: JSON.stringify({ provider }) }),
  models: (provider: string) => j<any>(`/api/models?provider=${encodeURIComponent(provider)}`),
  registry: () => j<any>('/api/registry'),
  project: () => j<any>('/api/project'),
  skills: () => j<{ skills: Skill[] }>('/api/skills'),
  skill: (name: string) => j<{ name: string; content: string; description: string; body: string }>(`/api/skills/${encodeURIComponent(name)}`),
  saveSkill: (b: { name: string; description: string; content: string; scope: SkillScope }) => j<any>('/api/skills', { method: 'POST', body: JSON.stringify(b) }),
  deleteSkill: (name: string, scope: SkillScope) => j<any>(`/api/skills/${encodeURIComponent(name)}?scope=${scope}`, { method: 'DELETE' }),
  skillLibrary: () => j<{ categories: string[]; skills: LibrarySkill[] }>('/api/skills/library'),
  addLibrarySkills: (names: string[], scope: SkillScope) => j<{ added: string[] }>('/api/skills/library', { method: 'POST', body: JSON.stringify({ names, scope }) }),
  importPreview: (url: string) => j<ImportPreview>('/api/skills/import/preview', { method: 'POST', body: JSON.stringify({ url }) }),
  importSkills: (url: string, names: string[], scope: SkillScope, overwrite: boolean) =>
    j<{ added: string[]; skipped: { name: string; reason: string }[]; source: string }>('/api/skills/import', { method: 'POST', body: JSON.stringify({ url, names, scope, overwrite }) }),
  browse: (path?: string) => j<any>(`/api/browse${path ? `?path=${encodeURIComponent(path)}` : ''}`, undefined, { pin: true }),
  execTool: (tool: string, args: any) => j<any>('/api/tools/execute', { method: 'POST', body: JSON.stringify({ tool, args }) }),
  gitStatus: () => j<any>('/api/git/status'),
  gitDiff: (path = '.') => j<any>(`/api/git/diff?path=${encodeURIComponent(path)}`),
  gitDiffCached: () => j<any>('/api/git/diff?cached=true'),
  gitCommit: (message: string) => j<any>('/api/git/commit', { method: 'POST', body: JSON.stringify({ message }) }),
  gitStage: (paths: string[]) => j<any>('/api/git/stage', { method: 'POST', body: JSON.stringify({ paths }) }),
  hfSearch: (q: string) => j<any>(`/api/hf/search?q=${encodeURIComponent(q)}`),
  hfDetails: (repo: string) => j<any>(`/api/hf/details?repo=${encodeURIComponent(repo)}`),
  hfDownload: (repo: string) => j<any>('/api/hf/download', { method: 'POST', body: JSON.stringify({ repo }) }),
  termExec: (command: string) => j<any>('/api/terminal/exec', { method: 'POST', body: JSON.stringify({ command }) }),
  threads: () => j<any>('/api/threads', undefined, { pin: true }),
  createThread: (title: string) => j<any>('/api/threads', { method: 'POST', body: JSON.stringify({ title }) }, { pin: true }),
  getThread: (id: string) => j<any>(`/api/threads/${id}`, undefined, { pin: true }),
  renameThread: (id: string, title: string, folder?: string) =>
    j<any>(`/api/threads/${id}`, { method: 'PATCH', body: JSON.stringify(folder ? { title, folder } : { title }) }, { pin: true }),
  deleteThread: (id: string) => j<any>(`/api/threads/${id}`, { method: 'DELETE' }, { pin: true }),
  appendMsg: (id: string, role: string, content: string) =>
    j<any>(`/api/threads/${id}/messages`, { method: 'POST', body: JSON.stringify({ role, content }) }, { pin: true }),
  automations: () => j<any>('/api/automations', undefined, { pin: true }),
  saveAutomation: (name: string, prompt: string) =>
    j<any>('/api/automations', { method: 'POST', body: JSON.stringify({ name, prompt }) }, { pin: true }),
  deleteAutomation: (id: string) => j<any>(`/api/automations/${id}`, { method: 'DELETE' }, { pin: true }),
  runAutomation: (id: string) => j<any>(`/api/automations/${id}/run`, { method: 'POST', body: JSON.stringify({}) }, { pin: true }),
  openFolder: () => j<any>('/api/project/open', { method: 'POST', body: JSON.stringify({}) }),
  mcpServers: (format?: string) => j<any>(`/api/mcp/servers${format ? `?format=${format}` : ''}`, undefined, { pin: true }),
  importMcp: (config: any) => j<any>('/api/mcp/import', { method: 'POST', body: JSON.stringify({ config }) }, { pin: true }),
  addMcpServer: (b: any) => j<any>('/api/mcp/servers', { method: 'POST', body: JSON.stringify(b) }, { pin: true }),
  toggleMcpServer: (name: string, enabled: boolean) =>
    j<any>(`/api/mcp/servers/${name}`, { method: 'PATCH', body: JSON.stringify({ enabled }) }, { pin: true }),
  deleteMcpServer: (name: string) => j<any>(`/api/mcp/servers/${name}`, { method: 'DELETE' }, { pin: true }),
  mcpTools: (name: string) => j<any>(`/api/mcp/servers/${name}/tools`),
  mcpCall: (server: string, tool: string, args: any) =>
    j<any>('/api/mcp/call', { method: 'POST', body: JSON.stringify({ server, tool, args }) }),
  imagesSupport: () => j<any>('/api/images/support'),
  imagesList: () => j<any>('/api/images'),
  generateImage: (provider: string, model: string, prompt: string, size: string) =>
    j<any>('/api/images/generate', { method: 'POST', body: JSON.stringify({ provider, model, prompt, size }) }),
  deleteImage: (id: string) => j<any>(`/api/images/${id}`, { method: 'DELETE' }),
  addCustomProvider: (b: { label: string; baseUrl: string; apiKey?: string }) =>
    j<{ id: string; label: string; baseUrl: string }>('/api/providers/custom', { method: 'POST', body: JSON.stringify(b) }),
  deleteCustomProvider: (id: string) => j<any>(`/api/providers/custom/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  updateStatus: () => j<any>('/api/update'),
  checkForUpdates: () => j<any>('/api/update/check', { method: 'POST', body: '{}' }),
  setAutoUpdate: (auto: boolean) => j<any>('/api/update/settings', { method: 'POST', body: JSON.stringify({ auto }) }),
  restartToUpdate: () => j<any>('/api/update/restart', { method: 'POST', body: '{}' }),
  remote: () => j<any>('/api/remote'),
  setRemote: (enabled: boolean) => j<any>('/api/remote/settings', { method: 'POST', body: JSON.stringify({ enabled }) }),
  approveRemotePair: (id: string) => j<any>(`/api/remote/pair/${encodeURIComponent(id)}/approve`, { method: 'POST', body: '{}' }),
  denyRemotePair: (id: string) => j<any>(`/api/remote/pair/${encodeURIComponent(id)}/deny`, { method: 'POST', body: '{}' }),
  setRemoteAuto: (id: string, allow: boolean) => j<any>(`/api/remote/devices/${encodeURIComponent(id)}/auto`, { method: 'POST', body: JSON.stringify({ allow }) }),
  forgetRemote: (id: string) => j<any>(`/api/remote/devices/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  shareRemoteProject: (path: string, share: boolean) => j<any>('/api/remote/projects', { method: 'POST', body: JSON.stringify({ path, share }) }),
  setRemoteFull: (id: string, allow: boolean) => j<any>(`/api/remote/devices/${encodeURIComponent(id)}/full`, { method: 'POST', body: JSON.stringify({ allow }) }),
  cloudSync: () => j<any>('/api/cloud/sync'),
  setCloudSync: (enabled: boolean) => j<any>('/api/cloud/sync', { method: 'POST', body: JSON.stringify({ enabled }) }),
  rememberWorkspaces: (paths: string[]) => j<any>('/api/cloud/workspaces', { method: 'POST', body: JSON.stringify({ paths, workspace: null }) }),
  account: () => j<any>('/api/account'),
  accountLogin: (provider: string, link = false) =>
    j<{ loginId: string; url: string; interval: number }>('/api/account/login', { method: 'POST', body: JSON.stringify({ provider, link }) }),
  pollAccountLogin: (loginId: string) => j<any>(`/api/account/poll/${encodeURIComponent(loginId)}`, { method: 'POST', body: '{}' }),
  cancelAccountLogin: (loginId: string) => j<any>(`/api/account/login/${encodeURIComponent(loginId)}`, { method: 'DELETE' }),
  accountLogout: () => j<any>('/api/account/logout', { method: 'POST', body: '{}' }),
  revokeAccountDevice: (id: string) => j<any>(`/api/account/devices/${encodeURIComponent(id)}/revoke`, { method: 'POST', body: '{}' }),
  unlinkAccount: (provider: string) => j<any>(`/api/account/identities/${encodeURIComponent(provider)}`, { method: 'DELETE' }),
  deleteAccount: () => j<any>('/api/account', { method: 'DELETE' }),
  agentSession: (id: string) => j<any>(`/api/agent/session/${id}`, undefined, { pin: true }),
  rewind: (threadId: string, turn: number, files = true, conversation = true) =>
    j<any>('/api/agent/rewind', { method: 'POST', body: JSON.stringify({ threadId, turn, files, conversation }) }, { pin: true }),
  compact: (threadId: string, provider: string, model: string) =>
    j<any>('/api/agent/compact', { method: 'POST', body: JSON.stringify({ threadId, provider, model }) }, { pin: true }),
  hooks: () => j<any>('/api/hooks'),
  trustHooks: () => j<any>('/api/hooks/trust', { method: 'POST', body: JSON.stringify({}) }),
  permissions: () => j<{ allow: string[] }>('/api/permissions'),
  savePermissions: (allow: string[]) => j<{ allow: string[] }>('/api/permissions', { method: 'POST', body: JSON.stringify({ allow }) }),
  webSearch: () => j<{ provider: string; baseUrl: string; hasKey: boolean }>('/api/websearch'),
  saveWebSearch: (b: { provider: string; apiKey?: string; baseUrl?: string }) =>
    j<{ provider: string; baseUrl: string; hasKey: boolean }>('/api/websearch', { method: 'POST', body: JSON.stringify(b) }),
  branch: async () => { try { const r = await api.execTool('git_branch', {}); return r.output?.stdout?.trim() || 'master'; } catch { return '—'; } },
};

export function imgUrl(id: string) {
  const ws = OV || WS;
  return `${BASE}/api/images/${id}/file${ws ? `?workspace=${encodeURIComponent(ws)}` : ''}`;
}

export async function* sse<T = any>(url: string, body: any, signal?: AbortSignal): AsyncGenerator<T> {
  const w = inject(url, { method: 'POST', body: JSON.stringify(body), signal } as any);
  const r = await transport(BASE + w.url, { method: 'POST', headers: { 'content-type': 'application/json' }, body: (w.init as any)?.body, signal });
  if (!r.ok || !r.body) throw new Error(`SSE failed: ${r.status}`);
  const reader = r.body.getReader();
  const dec = new TextDecoder();
  let buf = '';
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += dec.decode(value, { stream: true });
    const parts = buf.split('\n\n');
    buf = parts.pop() || '';
    for (const p of parts) {
      const line = p.split('\n').find((l) => l.startsWith('data:'));
      if (!line) continue;
      try { yield JSON.parse(line.slice(5).trim()); } catch { /* keep going */ }
    }
  }
}

export type LibrarySkill = { name: string; category: string; description: string; content: string; installed: boolean };
export type ImportPreview = { source: string; ref: string;
  skills: { path: string; name: string; description: string; chars: number; exists: boolean; ok: boolean; reason: string }[] };
