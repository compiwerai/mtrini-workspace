import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { api, type ImportPreview, type LibrarySkill, type Skill, type SkillScope } from '../api/client';
import { I } from './Icon';

type Draft = { name: string; description: string; content: string; scope: SkillScope; isNew: boolean };
type Panel = 'library' | 'import' | null;
const SLUG = /^[a-z0-9][a-z0-9-]{0,62}$/;
const errText = (e: any) => String(e?.message || e).replace(/^\d+\s*/, '').replace(/^\{"detail":"(.*)"\}$/, '$1');

/** Skill library: ready-made skills by category, each added in one click or opened in the editor. */
function Library({ lib, categories, onAdd, onCustomize }: {
  lib: LibrarySkill[]; categories: string[];
  onAdd: (s: LibrarySkill) => void; onCustomize: (s: LibrarySkill) => void;
}) {
  const [cat, setCat] = useState('All');
  const [q, setQ] = useState('');
  const shown = lib.filter((s) => (cat === 'All' || s.category === cat)
    && (!q.trim() || s.name.includes(q.trim().toLowerCase()) || s.description.toLowerCase().includes(q.trim().toLowerCase())));
  return (
    <div className="library">
      <div className="row" style={{ alignItems: 'baseline', justifyContent: 'space-between' }}>
        <h3>Skill library</h3>
        <span className="hint">{lib.filter((s) => s.installed).length} of {lib.length} added</span>
      </div>
      <p className="hint">Ready-made skills. Add one as it is, or open it in the editor and make it yours.</p>
      <div className="searchfield" style={{ margin: '12px 0 8px' }}>
        {I.search()}
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search the library" aria-label="Search the library" />
      </div>
      <div className="cattabs" role="tablist" aria-label="Categories">
        {['All', ...categories].map((c) => (
          <button key={c} role="tab" aria-selected={cat === c} className={cat === c ? 'on' : ''} onClick={() => setCat(c)}>{c}</button>
        ))}
      </div>
      <div className="templates">
        {shown.map((s) => (
          <div key={s.name} className="card template">
            <div className="row" style={{ justifyContent: 'space-between', alignItems: 'baseline' }}>
              <strong className="mono">/{s.name}</strong>
              <span className="hint">{s.category}</span>
            </div>
            <p className="hint">{s.description}</p>
            <div className="row">
              {s.installed
                ? <span className="hint">{I.check()} Added</span>
                : <button className="btn" onClick={() => onAdd(s)}>{I.plus()} Add</button>}
              <button className="btn" onClick={() => onCustomize(s)}>Customize</button>
            </div>
          </div>
        ))}
        {shown.length === 0 && <p className="hint">No skills match.</p>}
      </div>
    </div>
  );
}

/** Import from GitHub: find SKILL.md files at a link, show them, write only the ones picked. */
function ImportGitHub({ onDone }: { onDone: (added: string[]) => void }) {
  const [url, setUrl] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [found, setFound] = useState<ImportPreview | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [scope, setScope] = useState<SkillScope>('project');
  const [overwrite, setOverwrite] = useState(false);
  const [result, setResult] = useState<string | null>(null);

  const find = async () => {
    if (!url.trim()) return;
    setBusy(true); setErr(null); setFound(null); setResult(null);
    try {
      const f = await api.importPreview(url.trim());
      setFound(f);
      setPicked(new Set(f.skills.filter((s) => s.ok && !s.exists).map((s) => s.name)));
    } catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  };
  const run = async () => {
    if (!found || picked.size === 0) return;
    setBusy(true); setErr(null);
    try {
      const r = await api.importSkills(url.trim(), [...picked], scope, overwrite);
      const skipped = r.skipped.length ? ` Skipped: ${r.skipped.map((s) => `/${s.name} (${s.reason.toLowerCase()})`).join(', ')}.` : '';
      setResult(`Imported ${r.added.length} skill${r.added.length === 1 ? '' : 's'} from ${r.source}.${skipped}`);
      onDone(r.added);
      await find();
    } catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  };
  const toggle = (name: string) => setPicked((p) => { const n = new Set(p); n.has(name) ? n.delete(name) : n.add(name); return n; });

  return (
    <div className="skill-import">
      <h3>Import from GitHub</h3>
      <p className="hint">Paste a repository, a folder or a SKILL.md link, like <code>github.com/owner/repo</code> or just <code>owner/repo</code>.
        Only the SKILL.md instructions are imported; scripts and other files are never downloaded or run.</p>
      <div className="notice" role="note">Imported skills become instructions the agent follows. Only import from sources you trust, and read a skill before you use it.</div>
      <form className="row" style={{ marginTop: 12 }} onSubmit={(e) => { e.preventDefault(); find(); }}>
        <input className="t" style={{ flex: 1 }} value={url} onChange={(e) => setUrl(e.target.value)} placeholder="github.com/owner/repo" aria-label="GitHub link" />
        <button className="btn primary" type="submit" disabled={busy || !url.trim()}>{busy && !found ? 'Searching…' : 'Find skills'}</button>
      </form>
      {err && <div className="notice" role="alert" style={{ marginTop: 10 }}>{err}</div>}
      {result && <div className="hint" role="status" style={{ marginTop: 10 }}>{result}</div>}
      {found && (
        <>
          <label className="f">Found {found.skills.length} in {found.source} ({found.ref})</label>
          <ul className="importlist">
            {found.skills.map((s) => (
              <li key={s.path}>
                <label className={s.ok ? '' : 'off'}>
                  <input type="checkbox" checked={picked.has(s.name)} disabled={!s.ok || (s.exists && !overwrite)} onChange={() => toggle(s.name)} />
                  <span className="mono">/{s.name || '?'}</span>
                  <span className="hint">{s.description}</span>
                  {!s.ok && <span className="hint">{s.reason}</span>}
                  {s.ok && s.exists && <span className="hint">Already installed</span>}
                </label>
              </li>
            ))}
          </ul>
          <div className="row" style={{ marginTop: 12, alignItems: 'center' }}>
            <select className="t" value={scope} onChange={(e) => setScope(e.target.value as SkillScope)} aria-label="Install to">
              <option value="project">This project</option>
              <option value="global">All projects</option>
            </select>
            <label className="hint" style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <input type="checkbox" checked={overwrite} onChange={(e) => setOverwrite(e.target.checked)} /> Replace skills I already have
            </label>
            <button className="btn primary" onClick={run} disabled={busy || picked.size === 0}>
              {busy ? 'Importing…' : `Import ${picked.size} skill${picked.size === 1 ? '' : 's'}`}
            </button>
          </div>
        </>
      )}
    </div>
  );
}

export default function SkillsView({ onUse }: { onUse: (text: string) => void }) {
  const [skills, setSkills] = useState<Skill[]>([]);
  const [lib, setLib] = useState<LibrarySkill[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState<Skill | null>(null);
  const [detail, setDetail] = useState<{ description: string; body: string } | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [panel, setPanel] = useState<Panel>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [s, l] = await Promise.all([api.skills(), api.skillLibrary().catch(() => ({ categories: [], skills: [] }))]);
      setSkills(s.skills || []); setLib(l.skills); setCategories(l.categories); setError(null);
    } catch { setError('Could not load skills. Is the backend running?'); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (!selected) { setDetail(null); return; }
    let live = true;
    api.skill(selected.name).then((d) => { if (live) setDetail({ description: d.description, body: d.body }); })
      .catch(() => { if (live) setDetail({ description: selected.description, body: '(unavailable)' }); });
    return () => { live = false; };
  }, [selected]);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? skills.filter((s) => s.name.includes(q) || s.description.toLowerCase().includes(q)) : skills;
  }, [skills, query]);

  const open = (p: Panel) => { setSelected(null); setDraft(null); setError(null); setPanel(p); };
  const startNew = (t?: { name: string; description: string; content: string }) => {
    setSelected(null); setPanel(null); setError(null);
    setDraft({ name: t?.name || '', description: t?.description || '', content: t?.content || '', scope: 'project', isNew: true });
  };

  const save = async () => {
    if (!draft) return;
    if (!SLUG.test(draft.name)) { setError('Name: lowercase letters, numbers and dashes, starting with a letter or number.'); return; }
    if (!draft.description.trim() || !draft.content.trim()) { setError('Add a one-line description and the instructions.'); return; }
    setSaving(true);
    try {
      await api.saveSkill({ name: draft.name, description: draft.description, content: draft.content, scope: draft.scope });
      await load();
      setSelected({ name: draft.name, scope: draft.scope, description: draft.description });
      setDraft(null);
      setError(null);
    } catch (e: any) { setError(errText(e)); } finally { setSaving(false); }
  };

  const remove = async (s: Skill) => {
    if (!confirm(`Delete the skill "${s.name}"? This removes its SKILL.md file.`)) return;
    try { await api.deleteSkill(s.name, s.scope); setSelected(null); await load(); }
    catch (e: any) { setError(`Delete failed: ${e.message || e}`); }
  };

  const addFromLibrary = async (s: LibrarySkill) => {
    try { await api.addLibrarySkills([s.name], 'project'); await load(); }
    catch (e: any) { setError(`Could not add /${s.name}: ${errText(e)}`); }
  };

  const showPanel = panel ?? (!selected && !draft ? 'library' : null);

  return (
    <div className="skills">
      <aside className="skills-list" aria-label="Skills">
        <div className="skills-head">
          <h2>Skills</h2>
          <button className="btn primary" onClick={() => startNew()}>{I.plus()} New skill</button>
        </div>
        <div className="row" style={{ gap: 6, margin: '8px 0' }}>
          <button className={`btn ${showPanel === 'library' ? 'on' : ''}`} onClick={() => open('library')}>Browse library</button>
          <button className={`btn ${showPanel === 'import' ? 'on' : ''}`} onClick={() => open('import')}>Import from GitHub</button>
        </div>
        <p className="hint">Reusable instructions for the agent. Type <code>/name</code> in a session to use one.</p>
        <div className="searchfield">
          {I.search()}
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search my skills" aria-label="Search my skills" />
        </div>
        {loading ? <div className="hint" style={{ padding: 12 }}>Loading…</div> : (
          <ul>
            {shown.map((s) => (
              <li key={s.scope + s.name}>
                <button className={`skillrow ${selected?.name === s.name && selected?.scope === s.scope && !draft ? 'on' : ''}`}
                  onClick={() => { setDraft(null); setPanel(null); setError(null); setSelected(s); }}>
                  <span className="skillname">/{s.name}</span>
                  <span className={`scope scope-${s.scope}`}>{s.scope}</span>
                  <span className="skilldesc">{s.description}</span>
                </button>
              </li>
            ))}
            {shown.length === 0 && skills.length > 0 && <li className="hint" style={{ padding: 12 }}>No skills match.</li>}
            {skills.length === 0 && <li className="hint" style={{ padding: 12 }}>No skills yet. Add some from the library.</li>}
          </ul>
        )}
      </aside>

      <section className="skills-detail" aria-live="polite">
        {error && <div className="notice" role="alert">{error}</div>}

        {draft ? (
          <div className="skill-editor">
            <h3>{draft.isNew ? 'New skill' : `Edit /${draft.name}`}</h3>
            <label className="f" htmlFor="sk-name">Name</label>
            <div className="slashinput">
              <span>/</span>
              <input id="sk-name" className="t" value={draft.name} disabled={!draft.isNew}
                onChange={(e) => setDraft({ ...draft, name: e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, '-') })} placeholder="code-review" />
            </div>
            <label className="f" htmlFor="sk-desc">Description</label>
            <input id="sk-desc" className="t" value={draft.description} maxLength={300}
              onChange={(e) => setDraft({ ...draft, description: e.target.value })} placeholder="One line: what this skill does and when to use it" />
            <label className="f" htmlFor="sk-scope">Available in</label>
            <select id="sk-scope" className="t" value={draft.scope} disabled={!draft.isNew}
              onChange={(e) => setDraft({ ...draft, scope: e.target.value as SkillScope })}>
              <option value="project">This project (.mtrini/skills)</option>
              <option value="global">All projects (~/.mtrini/skills)</option>
            </select>
            <label className="f" htmlFor="sk-body">Instructions</label>
            <textarea id="sk-body" className="t mono" rows={14} value={draft.content}
              onChange={(e) => setDraft({ ...draft, content: e.target.value })}
              placeholder={'Step-by-step instructions the agent should follow.\nMarkdown is fine.'} />
            <div className="row" style={{ marginTop: 14 }}>
              <button className="btn primary" onClick={save} disabled={saving}>{saving ? 'Saving…' : 'Save skill'}</button>
              <button className="btn" onClick={() => { setDraft(null); setError(null); }}>Cancel</button>
            </div>
            {draft.isNew && lib.length > 0 && (
              <>
                <label className="f">Start from the library</label>
                <div className="chips">
                  {lib.slice(0, 12).map((t) => <button key={t.name} onClick={() => startNew(t)}>/{t.name}</button>)}
                </div>
              </>
            )}
          </div>
        ) : selected && detail ? (
          <div className="skill-view">
            <div className="row" style={{ alignItems: 'baseline' }}>
              <h3 className="mono">/{selected.name}</h3>
              <span className={`scope scope-${selected.scope}`}>{selected.scope}</span>
            </div>
            <p className="lead">{detail.description}</p>
            <div className="row" style={{ margin: '14px 0 18px' }}>
              <button className="btn primary" onClick={() => onUse(`/${selected.name} `)}>{I.send()} Use in session</button>
              <button className="btn" onClick={() => setDraft({ name: selected.name, description: detail.description, content: detail.body, scope: selected.scope, isNew: false })}>{I.pencil()} Edit</button>
              <button className="btn" onClick={() => remove(selected)}>{I.trash()} Delete</button>
            </div>
            <label className="f">Instructions</label>
            <pre className="skillbody">{detail.body}</pre>
          </div>
        ) : showPanel === 'import' ? (
          <ImportGitHub onDone={() => load()} />
        ) : (
          <Library lib={lib} categories={categories} onAdd={addFromLibrary} onCustomize={(s) => startNew(s)} />
        )}
      </section>
    </div>
  );
}
