import React from 'react';
import type { Bot } from './api';
import { cells } from './mascots';

// One line-icon set, one stroke.
const PATHS: Record<string, string> = {
  inbox: 'M3 13l2.5-8h13L21 13v5a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1v-5zm0 0h5l1 2h6l1-2h5',
  plus: 'M12 5v14M5 12h14',
  send: 'M5 12h14M13 6l6 6-6 6',
  stop: 'M7 7h10v10H7z',
  globe: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM3 12h18M12 3c2.5 2.6 3.8 5.6 3.8 9s-1.3 6.4-3.8 9c-2.5-2.6-3.8-5.6-3.8-9S9.500 5.6 12 3z',
  pause: 'M9 6v12M15 6v12',
  play: 'M8 5l11 7-11 7V5z',
  phone: 'M8 3h8a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H8a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1zm3 15h2',
  code: 'M9 8l-4 4 4 4M15 8l4 4-4 4',
  check: 'M5 12.5l4.5 4.500L19 7.500',
  x: 'M6 6l12 12M18 6L6 18',
  chevron: 'M9 6l6 6-6 6',
  trash: 'M5 7h14M10 7V4h4v3M7 7l1 13h8l1-13',
  clock: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zm0 4.500V12l3 2',
  folder: 'M3 6.500a1 1 0 0 1 1-1h5l2 2.500h9a1 1 0 0 1 1 1V18a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V6.500z',
};

export function Icon({ name }: { name: keyof typeof PATHS | string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.500" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={PATHS[name] || ''} />
    </svg>
  );
}

// A bot's face: its pixel mascot on a dark tile, like the camel in the Mtrini logo.
export function Avatar({ bot, size, status }: { bot: Pick<Bot, 'name' | 'color'> & { mascot?: string; paused?: boolean }; size?: 'lg' | 'md'; status?: string }) {
  return (
    <span className={`avatar ${size || ''}`} aria-hidden="true">
      <svg viewBox="0 0 14 14" shapeRendering="crispEdges">
        {cells(bot.mascot || 'camel', bot.color, bot.paused).map(([x, y, fill]) => <rect key={`${x}-${y}`} x={x + 1} y={y + 1} width="1" height="1" fill={fill} />)}
      </svg>
      {status ? <i className={bot.paused ? 'paused' : status === 'queued' ? 'working' : status} /> : null}
    </span>
  );
}

const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

function inline(s: string): string {
  let out = esc(s);
  out = out.replace(/`([^`]+)`/g, '<code>$1</code>');
  out = out.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noreferrer noopener">$1</a>');
  out = out.replace(/(^|[\s(])(https?:\/\/[^\s<)]+)/g, '$1<a href="$2" target="_blank" rel="noreferrer noopener">$2</a>');
  out = out.replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>');
  return out;
}

// Small Markdown: paragraphs, bullet and numbered lists, headings, links, bold, inline code. Everything else is text.
export function toHtml(text: string): string {
  const blocks: string[] = [];
  let list: string[] = [];
  let para: string[] = [];
  const flush = () => {
    if (list.length) { blocks.push('<ul>' + list.map((l) => `<li>${inline(l)}</li>`).join('') + '</ul>'); list = []; }
    if (para.length) { blocks.push('<p>' + para.map(inline).join('<br/>') + '</p>'); para = []; }
  };
  let code: string[] | null = null;
  for (const raw of (text || '').split(/\r?\n/)) {
    if (/^\s*```/.test(raw)) {  // a fenced block: shown as written
      if (code) { blocks.push(`<pre>${esc(code.join('\n'))}</pre>`); code = null; } else { flush(); code = []; }
      continue;
    }
    if (code) { code.push(raw); continue; }
    const line = raw.trimEnd();
    const bullet = line.match(/^\s*(?:[-*•]|\d+[.)])\s+(.*)$/);
    const head = line.match(/^#{1,6}\s+(.*)$/);
    if (!line.trim()) flush();
    else if (head) { flush(); blocks.push(`<h4>${inline(head[1])}</h4>`); }
    else if (bullet) { if (para.length) flush(); list.push(bullet[1]); }
    else { if (list.length) flush(); para.push(line); }
  }
  flush();
  if (code) blocks.push(`<pre>${esc(code.join('\n'))}</pre>`);  // a fence left open
  return blocks.join('');
}

export function Rich({ text, className }: { text: string; className?: string }) {
  return <div className={`rich ${className || ''}`} dangerouslySetInnerHTML={{ __html: toHtml(text) }} />;
}

export function Dialog({ title, intro, onClose, children }: { title: string; intro?: string; onClose: () => void; children: React.ReactNode }) {
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);
  return (
    <div className="scrim" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="dialog" role="dialog" aria-modal="true" aria-label={title}>
        <h2>{title}</h2>
        {intro ? <p>{intro}</p> : <p />}
        {children}
      </div>
    </div>
  );
}
