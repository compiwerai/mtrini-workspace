const BASE = (import.meta as any).env?.VITE_API || '';

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

async function j<T>(url: string, init?: RequestInit, opts?: { pin?: boolean }): Promise<T> {
  const w = inject(url, init, opts?.pin);
  const r = await fetch(BASE + w.url, { ...w.init, headers: { 'content-type': 'application/json', ...(w.init?.headers || {}) } });
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
  branch: async () => { try { const r = await api.execTool('git_branch', {}); return r.output?.stdout?.trim() || 'master'; } catch { return '—'; } },
};

export function imgUrl(id: string) {
  const ws = OV || WS;
  return `${BASE}/api/images/${id}/file${ws ? `?workspace=${encodeURIComponent(ws)}` : ''}`;
}

export async function* sse<T = any>(url: string, body: any, signal?: AbortSignal): AsyncGenerator<T> {
  const w = inject(url, { method: 'POST', body: JSON.stringify(body), signal } as any);
  const r = await fetch(BASE + w.url, { method: 'POST', headers: { 'content-type': 'application/json' }, body: (w.init as any)?.body, signal });
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
