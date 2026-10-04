import React, { useEffect, useState } from 'react';
import { api } from '../api/client';
import { I } from './Icon';

// MCP dev tools: manage servers, inspect their tools, run calls manually.
export default function MCPView() {
  const [servers, setServers] = useState<any[]>([]);
  const [name, setName] = useState('');
  const [transport, setTransport] = useState<'stdio' | 'http'>('stdio');
  const [command, setCommand] = useState('npx');
  const [args, setArgs] = useState('-y @modelcontextprotocol/server-filesystem /tmp');
  const [url, setUrl] = useState('http://localhost:8000/mcp');
  const [err, setErr] = useState('');
  const [sel, setSel] = useState('');
  const [tools, setTools] = useState<any[]>([]);
  const [toolsErr, setToolsErr] = useState('');
  const [runTool, setRunTool] = useState('');
  const [runArgs, setRunArgs] = useState('{}');
  const [result, setResult] = useState('');
  const [busy, setBusy] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [importText, setImportText] = useState('{\n  "mcpServers": {\n    "fs": {\n      "command": "npx",\n      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]\n    }\n  }\n}');
  const [showJson, setShowJson] = useState<string | null>(null);

  const load = async () => {
    try { setServers((await api.mcpServers()).servers || []); } catch { setServers([]); }
  };
  useEffect(() => { load(); }, []);

  const add = async () => {
    setErr('');
    try {
      await api.addMcpServer(transport === 'stdio'
        ? { name, transport, command, args: args.split(/\s+/).filter(Boolean) }
        : { name, transport, url });
      setName(''); load();
    } catch (e: any) { setErr(String(e.message || e).slice(0, 300)); }
  };

  const doImport = async () => {
    setErr('');
    try {
      const cfg = JSON.parse(importText);
      const r = await api.importMcp(cfg);
      setShowImport(false);
      load();
      if (r.errors?.length) setErr(`Imported ${r.added.length}, skipped: ${r.errors.join('; ').slice(0, 300)}`);
    } catch (e: any) { setErr(`Import failed: ${String(e.message || e).slice(0, 300)}`); }
  };

  const doExport = async () => {
    try {
      const blob = new Blob([JSON.stringify(await api.mcpServers('claude'), null, 2)], { type: 'application/json' });
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = 'mcp-servers.json';
      a.click();
      URL.revokeObjectURL(a.href);
    } catch (e: any) { setErr(String(e.message || e).slice(0, 200)); }
  };
  const inspect = async (n: string) => {
    setSel(n); setTools([]); setToolsErr(''); setResult('');
    try {
      const r = await api.mcpTools(n);
      setTools(r.tools || []);
      if (r.error) setToolsErr(r.error);
    } catch (e: any) { setToolsErr(String(e.message || e).slice(0, 300)); }
  };

  const run = async () => {
    if (!runTool) return;
    setBusy(true);
    setResult('');
    try {
      let a = {};
      try { a = JSON.parse(runArgs || '{}'); } catch { throw new Error('args must be valid JSON'); }
      const r = await api.mcpCall(sel, runTool, a);
      setResult(JSON.stringify(r.output ?? r, null, 2).slice(0, 8000));
    } catch (e: any) { setResult(`ERROR: ${String(e.message || e).slice(0, 500)}`); }
    finally { setBusy(false); }
  };

  return (
    <div className="view">
      <h2>MCP dev tools</h2>
      <p style={{ color: 'var(--muted)' }}>Connect Model Context Protocol servers. Enabled servers lend their tools to the agent (with approval). Inspect and run calls here. Config is plain JSON — import/export Claude-shaped files freely.</p>
      <div className="row" style={{ marginBottom: 8 }}>
        <button className="btn" onClick={() => setShowImport(true)}>Import JSON…</button>
        <button className="btn" onClick={doExport}>Export JSON</button>
      </div>
      <div className="card">
        <div className="row" style={{ flexWrap: 'wrap' }}>
          <input className="t" value={name} onChange={(e) => setName(e.target.value)} placeholder="server-name" aria-label="Server name" style={{ maxWidth: 180 }} />
          <select className="t" value={transport} onChange={(e) => setTransport(e.target.value as any)} style={{ maxWidth: 130 }} aria-label="Transport">
            <option value="stdio">stdio</option>
            <option value="http">http</option>
          </select>
          {transport === 'stdio' ? (
            <>
              <input className="t" value={command} onChange={(e) => setCommand(e.target.value)} placeholder="command" aria-label="Command" style={{ maxWidth: 140 }} />
              <input className="t" value={args} onChange={(e) => setArgs(e.target.value)} placeholder="args…" aria-label="Args" style={{ flex: 1, minWidth: 200 }} />
            </>
          ) : (
            <input className="t" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://…/mcp" aria-label="URL" style={{ flex: 1, minWidth: 200 }} />
          )}
          <button className="btn primary" onClick={add} disabled={!name.trim()}>Add</button>
        </div>
        {err && <p style={{ color: 'var(--danger)' }}>{err}</p>}
      </div>
      {servers.map((s) => (
        <div className="card" key={s.name}>
          <div className="row">
            <strong>{s.name}</strong>
            <span className="tag">{s.transport}{s.transport === 'stdio' ? ` · ${s.command}` : ` · ${s.url}`}</span>
            <span style={{ flex: 1 }} />
            <label className="row" style={{ fontSize: 12 }}>
              <input type="checkbox" checked={s.enabled !== false}
                onChange={() => api.toggleMcpServer(s.name, s.enabled === false).then(load)} /> enabled
            </label>
            <button className="btn" onClick={() => inspect(s.name)}>Inspect</button>
            <button className="btn" onClick={() => setShowJson(showJson === s.name ? null : s.name)}>JSON</button>
            <button className="btn" onClick={() => api.deleteMcpServer(s.name).then(() => { load(); if (sel === s.name) { setSel(''); setTools([]); } })}>{I.trash()}</button>
          </div>
          {showJson === s.name && (
            <pre style={{ fontSize: 11, whiteSpace: 'pre-wrap' }}>{JSON.stringify(s, null, 2)}</pre>
          )}
          {sel === s.name && (
            <div style={{ marginTop: 8 }}>
              {toolsErr && <p style={{ color: 'var(--danger)' }}>{toolsErr}</p>}
              {tools.map((t) => (
                <div key={t.name} style={{ borderTop: '1px solid var(--border)', padding: '8px 0' }}>
                  <div className="row"><code>{t.name}</code><span style={{ flex: 1 }} />
                    <button className="btn" onClick={() => { setRunTool(t.name); setRunArgs('{}'); }}>Use</button></div>
                  {t.description && <div style={{ color: 'var(--muted)', fontSize: 12 }}>{t.description}</div>}
                  <pre style={{ fontSize: 11, whiteSpace: 'pre-wrap' }}>{JSON.stringify(t.schema, null, 1).slice(0, 1200)}</pre>
                </div>
              ))}
              {tools.length === 0 && !toolsErr && <div style={{ color: 'var(--muted)' }}>No tools listed.</div>}
              {tools.length > 0 && (
                <div className="card" style={{ marginTop: 8 }}>
                  <div className="row">
                    <input className="t" value={runTool} onChange={(e) => setRunTool(e.target.value)} placeholder="tool name" aria-label="Tool" style={{ maxWidth: 200 }} />
                    <input className="t" value={runArgs} onChange={(e) => setRunArgs(e.target.value)} placeholder='{"key": "value"}' aria-label="Args JSON" style={{ flex: 1 }} />
                    <button className="btn primary" onClick={run} disabled={busy}>{busy ? '…' : 'Run'}</button>
                  </div>
                  {result && <pre style={{ fontSize: 11, whiteSpace: 'pre-wrap', maxHeight: 300, overflow: 'auto' }}>{result}</pre>}
                </div>
              )}
            </div>
          )}
        </div>
      ))}
      {servers.length === 0 && <div style={{ color: 'var(--muted)' }}>No MCP servers yet. Try the filesystem server via npx, or any streamable-HTTP endpoint.</div>}
      {showImport && (
        <div className="modal" onClick={() => setShowImport(false)} role="dialog" aria-label="Import MCP JSON">
          <div className="sheet" style={{ width: 560 }} onClick={(e) => e.stopPropagation()}>
            <strong>Import MCP JSON</strong>
            <p className="hint">Claude shape (<code>mcpServers</code>), an array, or a single server object.</p>
            <textarea className="t" rows={12} value={importText} onChange={(e) => setImportText(e.target.value)}
              style={{ fontFamily: 'var(--mono)', fontSize: 12 }} aria-label="JSON to import" />
            <div className="row" style={{ marginTop: 10 }}>
              <button className="btn primary" onClick={doImport}>Import</button>
              <button className="btn" onClick={() => setShowImport(false)}>Cancel</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
