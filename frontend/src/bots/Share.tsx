import React, { useEffect, useMemo, useRef, useState } from 'react';
import { api, type Bot, type Recipe, type Saved } from './api';
import { cardContent, copyImage, drawCard, toPng, whatsappLink, xLink, type CardData } from './card';
import { Avatar, Dialog, Icon } from './parts';

type Notify = (text: string, bad?: boolean) => void;
type Face = Pick<Bot, 'name' | 'role' | 'color' | 'mascot' | 'provider'>;

// The card itself, drawn on a canvas. The headline is also given as text, for screen readers.
export function CardCanvas({ data, canvasRef, className }: { data: CardData; canvasRef?: React.RefObject<HTMLCanvasElement>; className?: string }) {
  const own = useRef<HTMLCanvasElement>(null);
  const ref = canvasRef || own;
  const key = JSON.stringify(data);
  useEffect(() => { if (ref.current) drawCard(ref.current, data); }, [key]);  // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <figure className={`card ${className || ''}`}>
      <canvas ref={ref} width={1200} height={675} role="img" aria-label={`Card: ${data.headline}`} />
    </figure>
  );
}

export function cardData(bot: Face, text: string, title = '') {
  const c = cardContent(bot.name, text, title);
  return { content: c, data: { name: bot.name, role: bot.role, color: bot.color, mascot: bot.mascot, provider: bot.provider, headline: c.headline, lines: c.lines } as CardData };
}

// Preview first, then save, copy or post. Only what is in the preview goes on the card.
export function ShareCard({ bot, text, title, onClose, notify }: { bot: Face; text: string; title?: string; onClose: () => void; notify: Notify }) {
  const start = useMemo(() => cardData(bot, text, title), [bot.name, text, title]);  // eslint-disable-line react-hooks/exhaustive-deps
  const [headline, setHeadline] = useState(start.data.headline);
  const [lines, setLines] = useState(start.data.lines.join('\n'));
  const [saved, setSaved] = useState<Saved | null>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const data: CardData = { ...start.data, headline: headline.trim() || start.data.headline, lines: lines.split('\n').map((l) => l.trim()).filter(Boolean).slice(0, 4) };

  const save = async () => {
    if (!canvas.current) return;
    try { const s = await api.saveCard(toPng(canvas.current), bot.name); setSaved(s); notify('Card saved'); } catch (e: any) { notify(e.message, true); }
  };
  const copy = async (then?: string) => {
    const ok = canvas.current ? await copyImage(canvas.current) : false;
    if (then) {
      try { await api.open(then); } catch (e: any) { notify(e.message, true); return; }
      notify(ok ? 'Image copied. Paste it into your post.' : 'Save the image first, then add it to your post.', !ok);
    } else notify(ok ? 'Image copied' : 'This window cannot copy images. Save it instead.', !ok);
  };

  return (
    <Dialog title="Share as a card" intro="Only what you see goes on the card. It is made on this computer and nothing is uploaded until you post it."
      onClose={onClose} className="wide">
      <CardCanvas data={data} canvasRef={canvas} />
      {start.content.hidden.length ? (
        <p className="note">Hidden because it looked personal: {start.content.hidden.join(', ')}. Type it back in below if you want it on the card.</p>
      ) : null}
      <div className="field" style={{ marginTop: 16 }}><label htmlFor="c-head">Headline</label>
        <input id="c-head" value={headline} maxLength={90} onChange={(e) => setHeadline(e.target.value)} /></div>
      <div className="field"><label htmlFor="c-lines">Lines</label>
        <textarea id="c-lines" rows={4} value={lines} onChange={(e) => setLines(e.target.value)} />
        <small>One per line, up to four.</small></div>
      {saved ? (
        <div className="note saved">Saved to <span className="mono">{saved.path}</span>
          <button className="btn ghost" onClick={() => api.reveal(saved.path).catch((e) => notify(e.message, true))}>Show in folder</button></div>
      ) : null}
      <div className="foot">
        <button className="btn ghost tall" onClick={() => copy(xLink(data.headline))}>Post on X</button>
        <button className="btn ghost tall" onClick={() => copy(whatsappLink(data.headline))}>WhatsApp</button>
        <button className="btn tall" onClick={() => copy()}>Copy image</button>
        <button className="btn primary tall" onClick={save}><Icon name="download" />Save image</button>
      </div>
    </Dialog>
  );
}

// ---- recipes: a bot's job as a link ----
export function ShareRecipe({ bot, onClose, notify }: { bot: Bot; onClose: () => void; notify: Notify }) {
  const [link, setLink] = useState('');
  const [saved, setSaved] = useState<Saved | null>(null);
  useEffect(() => { api.recipe(bot.id).then((r) => setLink(r.link)).catch((e) => notify(e.message, true)); }, [bot.id, notify]);
  const copy = async () => {
    try { await navigator.clipboard.writeText(link); notify('Link copied'); } catch { notify('Select the link and copy it.', true); }
  };
  const save = async () => { try { setSaved(await api.saveRecipe(bot.id)); } catch (e: any) { notify(e.message, true); } };
  return (
    <Dialog title={`Share ${bot.name} as a recipe`} intro={`Anyone with Mtrini Bots can paste this to get their own ${bot.name}.`} onClose={onClose}>
      <div className="field"><label htmlFor="r-link">Recipe link</label>
        <input id="r-link" readOnly value={link} onFocus={(e) => e.currentTarget.select()} />
        <small>It holds the name, role, instructions and routines. Not the memory, files, conversation or model.</small></div>
      {saved ? (
        <div className="note saved">Saved to <span className="mono">{saved.path}</span>
          <button className="btn ghost" onClick={() => api.reveal(saved.path).catch((e) => notify(e.message, true))}>Show in folder</button></div>
      ) : null}
      <div className="foot">
        <button className="btn ghost tall" onClick={save}>Save as file</button>
        <button className="btn primary tall" disabled={!link} onClick={copy}>Copy link</button>
      </div>
    </Dialog>
  );
}

export function ImportRecipe({ onClose, onImported }: { onClose: () => void; onImported: (b: Bot) => void }) {
  const [text, setText] = useState('');
  const [recipe, setRecipe] = useState<Recipe | null>(null);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const preview = async (value = text) => {
    setErr(''); setRecipe(null);
    try { setRecipe((await api.previewRecipe(value)).recipe); } catch (e: any) { setErr(e.message); }
  };
  const fromFile = (f?: File) => {
    if (!f) return;
    f.text().then((t) => { setText(t); preview(t); }).catch(() => setErr('That file could not be read.'));
  };
  const add = async () => {
    setBusy(true);
    try { onImported(await api.importRecipe(text)); } catch (e: any) { setErr(e.message); setBusy(false); }
  };
  return (
    <Dialog title="Add a bot from a recipe" intro="Paste a recipe link someone shared, or open a recipe file." onClose={onClose}>
      {!recipe ? (
        <>
          <div className="field"><label htmlFor="i-text">Recipe link</label>
            <textarea id="i-text" rows={3} value={text} onChange={(e) => setText(e.target.value)} placeholder="https://compiwer.ai/bots/r#…" /></div>
          <label className="btn ghost filepick">Open a file<input type="file" accept=".json,application/json" onChange={(e) => fromFile(e.target.files?.[0])} /></label>
          {err ? <div className="err" role="alert">{err}</div> : null}
          <div className="foot"><button className="btn ghost tall" onClick={onClose}>Cancel</button>
            <button className="btn primary tall" disabled={!text.trim()} onClick={() => preview()}>Preview</button></div>
        </>
      ) : (
        <>
          <div className="recipe">
            <Avatar bot={{ name: recipe.name, color: recipe.color || '#5ad1e6', mascot: recipe.mascot }} size="md" />
            <div><b>{recipe.name}</b><small>{recipe.role || 'Assistant'}</small></div>
          </div>
          <div className="field"><span className="label">Its instructions</span>
            <pre className="instr">{recipe.instructions || 'None'}</pre>
            <small>Read them: this is what the bot will be told to do. It still asks before it acts for you.</small></div>
          {recipe.routines.length ? (
            <div className="field"><span className="label">Routines, switched off until you turn them on</span>
              <ul className="plainlist">{recipe.routines.map((r) => <li key={r.title}>{r.title}</li>)}</ul></div>
          ) : null}
          <p className="hint">It runs on the free built-in model. You can pick another in its settings.</p>
          {err ? <div className="err" role="alert">{err}</div> : null}
          <div className="foot"><button className="btn ghost tall" onClick={() => setRecipe(null)}>Back</button>
            <button className="btn primary tall" disabled={busy} onClick={add}>Add {recipe.name}</button></div>
        </>
      )}
    </Dialog>
  );
}
