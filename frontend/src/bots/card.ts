// A bot's result as a card to share: its pixel face, its name, a headline, a few lines, and the Mtrini mark.
// Drawn on this computer with a canvas; nothing is uploaded. Only what the user keeps in the preview is drawn.
import { cells } from './mascots';

export const SITE = 'compiwer.ai/bots';
export const SITE_URL = 'https://compiwer.ai/bots';
export const W = 1200;
export const H = 675;  // 16:9, the size X and WhatsApp show whole
const SCALE = 2;
const SANS = '"DM Sans Variable", "DM Sans", "Segoe UI", sans-serif';
const MONO = '"IBM Plex Mono", Consolas, monospace';
const FREE = ['free', 'compiwer-free'];

export type CardData = { name: string; role: string; color: string; mascot: string; provider: string; headline: string; lines: string[] };
export type CardContent = { headline: string; lines: string[]; hidden: string[] };

// ---- what goes on the card ----
const BULLET = /^(?:[-*•]|\d+[.)])\s+/;
const host = (url: string) => { try { return new URL(url).hostname.replace(/^www\./, ''); } catch { return ''; } };

/** Markdown and links down to plain words: a link becomes its text, a bare URL its site name. */
export function plain(s: string): string {
  return s
    .replace(/\[([^\]]+)\]\((?:https?:\/\/[^\s)]+)\)/g, '$1')
    .replace(/\(?<?(https?:\/\/[^\s<>)]+)>?\)?/g, (_m, url: string) => { const h = host(url.replace(/[.,;]+$/, '')); return h ? `(${h})` : ''; })
    .replace(/(\*{1,3}|`)([^*`]+)\1/g, '$2')
    .replace(/^#+\s*|^>\s*/g, '')
    .replace(/\s*[-–—:]\s*(\([^)]+\))$/, ' $1')
    .replace(/\s+/g, ' ')
    .trim();
}

const PERSONAL: [string, RegExp, (m: string) => boolean][] = [
  ['an email address', /[\w.+-]+@[\w-]+(?:\.[\w-]+)+/g, () => true],
  ['a phone or card number', /\+?\d[\d\s().-]{7,}\d/g, (m) => (m.match(/\d/g) || []).length >= 9 && !/^\d{4}-\d{2}-\d{2}/.test(m)],
  ['a folder on this computer', /(?:[A-Za-z]:\\|\/(?:Users|home)\/)[^\s)]+/g, () => true],
];

/** Hide what looks personal. The user can type it back in the preview: then it was their choice. */
export function mask(s: string): { text: string; hidden: string[] } {
  const hidden: string[] = [];
  let text = s;
  for (const [what, re, real] of PERSONAL) {
    text = text.replace(re, (m) => { if (!real(m)) return m; if (!hidden.includes(what)) hidden.push(what); return '[hidden]'; });
  }
  return { text, hidden };
}

const clip = (s: string, n: number) => (s.length > n ? `${s.slice(0, n - 1).trimEnd()}…` : s);

/** A headline and 2 to 4 lines from a bot's reply, ready to edit. */
export function cardContent(name: string, text: string, title = ''): CardContent {
  const rows = (text || '').split(/\r?\n/).map((r) => r.trim()).filter((r) => r && !/^```/.test(r) && !/^[-*_]{3,}$/.test(r));
  let headline = '';
  let body = rows;
  const first = rows[0] ? plain(rows[0]) : '';
  if (rows[0] && !BULLET.test(rows[0]) && first.length <= 80 && !first.endsWith(':')) { headline = first; body = rows.slice(1); }
  const bullets = body.filter((r) => BULLET.test(r)).map((r) => r.replace(BULLET, ''));
  const prose = body.filter((r) => !plain(r).endsWith(':')).flatMap((r) => plain(r).split(/(?<=[.!?])\s+(?=[A-Z])/));
  const lines = (bullets.length ? bullets.map(plain) : prose).filter((l) => l.length > 1).slice(0, 4).map((l) => clip(l, 140));
  if (!headline) {
    headline = bullets.length >= 2 ? `${name} found ${bullets.length} things for you`
      : title ? `${name}: ${title}` : `${name} finished a job for you`;
  }
  const hidden: string[] = [];
  const keep = (s: string) => { const m = mask(s); m.hidden.forEach((h) => { if (!hidden.includes(h)) hidden.push(h); }); return m.text; };
  return { headline: clip(keep(headline), 90), lines: lines.map(keep), hidden };
}

/** Lines that fit `max` wide, breaking at spaces (and inside a word only when it alone is too wide). */
export function wrap(text: string, max: number, measure: (s: string) => number): string[] {
  const out: string[] = [];
  let line = '';
  for (const word of text.split(/\s+/).filter(Boolean)) {
    const next = line ? `${line} ${word}` : word;
    if (measure(next) <= max) { line = next; continue; }
    if (line) out.push(line);
    line = word;
    while (measure(line) > max && line.length > 1) {
      let cut = line.length - 1;
      while (cut > 1 && measure(line.slice(0, cut)) > max) cut--;
      out.push(line.slice(0, cut));
      line = line.slice(cut);
    }
  }
  if (line) out.push(line);
  return out;
}

/** At most `rows` lines; the last one ends with … when text was left out. */
export function fit(text: string, max: number, rows: number, measure: (s: string) => number): string[] {
  const all = wrap(text, max, measure);
  if (all.length <= rows) return all;
  const kept = all.slice(0, rows);
  let last = `${kept[rows - 1]}…`;
  while (measure(last) > max && last.length > 2) last = `${last.slice(0, -2).trimEnd()}…`;
  kept[rows - 1] = last;
  return kept;
}

export const isFree = (provider: string) => FREE.includes(provider);

export function shareText(headline: string): string {
  return `${headline.replace(/[.!]+$/, '')}. Made with Mtrini Bots: free, open-source AI bots that run on your PC.`;
}
export const xLink = (headline: string) => `https://x.com/intent/post?text=${encodeURIComponent(shareText(headline))}&url=${encodeURIComponent(SITE_URL)}`;
export const whatsappLink = (headline: string) => `https://wa.me/?text=${encodeURIComponent(`${shareText(headline)} ${SITE_URL}`)}`;

// ---- drawing ----
function rounded(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

let fontsReady: Promise<unknown> | null = null;
function loadFonts(): Promise<unknown> {
  const fonts = (typeof document !== 'undefined' ? (document as any).fonts : null);
  if (!fonts?.load) return Promise.resolve();
  fontsReady ||= Promise.all(['500 58px "DM Sans Variable"', '400 29px "DM Sans Variable"', '400 18px "IBM Plex Mono"']
    .map((f) => fonts.load(f).catch(() => null)));
  return fontsReady;
}

/** Draw the card. Returns false where there is no canvas (tests, very old browsers). */
export async function drawCard(canvas: HTMLCanvasElement, d: CardData): Promise<boolean> {
  let ctx: CanvasRenderingContext2D | null = null;
  try { ctx = canvas.getContext('2d'); } catch { ctx = null; }
  if (!ctx) return false;
  await loadFonts();
  canvas.width = W * SCALE;
  canvas.height = H * SCALE;
  ctx.setTransform(SCALE, 0, 0, SCALE, 0, 0);
  ctx.textBaseline = 'alphabetic';
  const measure = (s: string) => ctx!.measureText(s).width;
  const L = 72;
  const R = W - 72;

  ctx.fillStyle = '#f4f4f5';
  ctx.fillRect(0, 0, W, H);
  rounded(ctx, 24, 24, W - 48, H - 48, 28);
  ctx.fillStyle = '#ffffff';
  ctx.fill();
  ctx.strokeStyle = 'rgba(23, 23, 23, 0.08)';
  ctx.lineWidth = 1;
  ctx.stroke();

  // the face, on a dark tile like the Mtrini camel
  const T = 120;
  rounded(ctx, L, 72, T, T, 26);
  ctx.fillStyle = '#17191d';
  ctx.fill();
  const px = T / 14;
  for (const [x, y, fill] of cells(d.mascot || 'camel', d.color)) {
    ctx.fillStyle = fill;
    ctx.fillRect(L + (x + 1) * px, 72 + (y + 1) * px, px + 0.5, px + 0.5);  // +0.5: no hairlines between cells
  }

  ctx.fillStyle = '#171717';
  ctx.font = `500 36px ${SANS}`;
  ctx.fillText(fit(d.name, R - L - T - 28, 1, measure)[0] || '', L + T + 28, 72 + 54);
  ctx.fillStyle = '#737373';
  ctx.font = `400 20px ${MONO}`;
  ctx.fillText(fit(d.role || 'Personal AI bot', R - L - T - 28, 1, measure)[0] || '', L + T + 28, 72 + 92);

  let y = 72 + T + 84;
  ctx.fillStyle = '#171717';
  ctx.font = `500 58px ${SANS}`;
  for (const row of fit(d.headline, R - L, 2, measure)) { ctx.fillText(row, L, y); y += 68; }

  y += 6;
  const bottom = H - 140;
  ctx.font = `400 29px ${SANS}`;
  for (const item of d.lines.slice(0, 4)) {
    if (y > bottom) break;
    const rows = fit(item, R - L - 34, y + 40 > bottom ? 1 : 2, measure);
    ctx.fillStyle = d.color || '#5ad1e6';
    ctx.fillRect(L, y - 18, 12, 12);  // a pixel, in the bot's colour
    ctx.fillStyle = '#404040';
    for (const row of rows) { if (y > bottom + 8) break; ctx.fillText(row, L + 34, y); y += 40; }
    y += 8;
  }

  ctx.fillStyle = 'rgba(23, 23, 23, 0.08)';
  ctx.fillRect(L, H - 112, R - L, 1);
  let x = L;
  const part = (text: string, font: string, color: string) => { ctx!.font = font; ctx!.fillStyle = color; ctx!.fillText(text, x, H - 66); x += measure(text); };
  part('Made with ', `400 19px ${MONO}`, '#737373');
  part('Mtrini Bots', `500 21px ${SANS}`, '#171717');
  part(`  ·  ${SITE}`, `400 19px ${MONO}`, '#737373');
  if (isFree(d.provider)) {
    ctx.font = `400 19px ${MONO}`;
    ctx.fillStyle = '#737373';
    ctx.textAlign = 'right';
    ctx.fillText('Free built-in model · runs on your PC', R, H - 66);
    ctx.textAlign = 'left';
  }
  return true;
}

export const toPng = (canvas: HTMLCanvasElement) => canvas.toDataURL('image/png');

export async function copyImage(canvas: HTMLCanvasElement): Promise<boolean> {
  const Item = (window as any).ClipboardItem;
  if (!Item || !navigator.clipboard?.write) return false;
  const blob: Blob | null = await new Promise((done) => canvas.toBlob(done, 'image/png'));
  if (!blob) return false;
  try { await navigator.clipboard.write([new Item({ 'image/png': blob })]); return true; } catch { return false; }
}
