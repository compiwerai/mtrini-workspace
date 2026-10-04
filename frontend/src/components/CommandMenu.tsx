import React, { useEffect, useMemo, useRef, useState } from 'react';
import { api } from '../api/client';
import { I } from './Icon';

export type ActionId =
  | 'new-thread' | 'go-files' | 'go-images' | 'go-mcp' | 'go-skills' | 'go-automations' | 'go-settings'
  | 'toggle-diff' | 'open-folder' | 'commit' | 'pick-workspace';

const ACTIONS: { id: ActionId; label: string; hint: string }[] = [
  { id: 'new-thread', label: 'New thread', hint: 'Ctrl+L' },
  { id: 'go-files', label: 'Go to Files', hint: '' },
  { id: 'go-images', label: 'Go to Images', hint: '' },
  { id: 'go-mcp', label: 'Go to MCP dev tools', hint: '' },
  { id: 'go-skills', label: 'Go to Skills', hint: '' },
  { id: 'go-automations', label: 'Go to Automations', hint: '' },
  { id: 'go-settings', label: 'Go to Settings', hint: 'Ctrl+,' },
  { id: 'toggle-diff', label: 'Toggle changes panel', hint: '' },
  { id: 'open-folder', label: 'Reveal folder in Explorer', hint: '' },
  { id: 'commit', label: 'Commit changes…', hint: '' },
  { id: 'pick-workspace', label: 'Switch working folder…', hint: '' },
];

type Item =
  | { kind: 'thread'; id: string; label: string; sub: string }
  | { kind: 'file'; id: string; label: string; sub: string }
  | { kind: 'action'; id: ActionId; label: string; sub: string };

export default function CommandMenu({ onClose, threads, onThread, onAction }: {
  onClose: () => void; threads: { id: string; title: string; preview: string }[];
  onThread: (id: string) => void; onAction: (a: ActionId) => void;
}) {
  const [q, setQ] = useState('');
  const [files, setFiles] = useState<string[]>([]);
  const [sel, setSel] = useState(0);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => { input.current?.focus(); }, []);
  useEffect(() => {
    if (q.trim().length < 2) { setFiles([]); return; }
    const t = setTimeout(async () => {
      try {
        const r = await api.execTool('search_filename', { pattern: q.trim(), limit: 8 });
        setFiles(r.ok ? r.output.files || [] : []);
      } catch { setFiles([]); }
    }, 200);
    return () => clearTimeout(t);
  }, [q]);

  const items: Item[] = useMemo(() => {
    const needle = q.toLowerCase();
    const match = (s: string) => !needle || s.toLowerCase().includes(needle);
    const out: Item[] = [
      ...threads.filter((t) => match(t.title)).slice(0, 6)
        .map((t): Item => ({ kind: 'thread', id: t.id, label: t.title, sub: t.preview.slice(0, 60) })),
      ...files.filter(match).map((f): Item => ({ kind: 'file', id: f, label: f, sub: 'file' })),
      ...ACTIONS.filter((a) => match(a.label)).map((a): Item => ({ kind: 'action', id: a.id, label: a.label, sub: a.hint })),
    ];
    return out.slice(0, 14);
  }, [q, threads, files]);

  useEffect(() => { setSel(0); }, [items.length]);

  const run = (it: Item) => {
    onClose();
    if (it.kind === 'thread') onThread(it.id);
    else if (it.kind === 'file') window.dispatchEvent(new CustomEvent('mtrini:open', { detail: it.id }));
    else onAction(it.id);
  };

  return (
    <div className="modal cmdmenu" onClick={onClose} role="dialog" aria-label="Command menu">
      <div className="cmdsheet" onClick={(e) => e.stopPropagation()}>
        <input ref={input} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Type a command, thread, or file…"
          aria-label="Command input"
          onKeyDown={(e) => {
            if (e.key === 'ArrowDown') { e.preventDefault(); setSel((s) => Math.min(s + 1, items.length - 1)); }
            if (e.key === 'ArrowUp') { e.preventDefault(); setSel((s) => Math.max(s - 1, 0)); }
            if (e.key === 'Enter' && items[sel]) run(items[sel]);
            if (e.key === 'Escape') onClose();
          }} />
        <div className="cmdlist">
          {items.map((it, i) => (
            <div key={`${it.kind}-${it.id}`} className={`cmd ${i === sel ? 'on' : ''}`} onClick={() => run(it)}>
              <span className="k">{it.kind === 'thread' ? I.file() : it.kind === 'file' ? I.file() : I.command()}</span>
              <span className="t">{it.label}</span>
              {it.sub && <kbd>{it.sub}</kbd>}
            </div>
          ))}
          {items.length === 0 && <div className="cmdempty">No matches.</div>}
        </div>
      </div>
    </div>
  );
}
