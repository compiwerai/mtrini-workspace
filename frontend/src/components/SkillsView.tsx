import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { api, type Skill, type SkillScope } from '../api/client';
import { I } from './Icon';

/** Starter skills offered when a project has none (or from "New skill"). */
const TEMPLATES: { name: string; description: string; content: string }[] = [
  {
    name: 'code-review',
    description: 'Review the current changes for bugs, risks and missing tests',
    content: `1. Run \`git diff\` (and \`git diff --cached\`) to see what changed.
2. Read each changed file around the edits, not just the diff hunks.
3. List problems by severity: bugs first, then risky behavior, then missing tests, then style.
4. For each problem give the file and line, what goes wrong, and a concrete fix.
5. Do not edit files unless the user asks you to apply the fixes.`,
  },
  {
    name: 'write-tests',
    description: 'Add focused tests for the code that was just changed',
    content: `1. Find the project's test framework and where existing tests live.
2. Cover the changed behavior: the main path, edge cases and one failure case.
3. Follow the style of nearby tests. Do not add new test dependencies without asking.
4. Run the tests and fix failures in the tests (not the code) unless the code is wrong.
5. Report which tests you added and the final test result.`,
  },
  {
    name: 'commit-message',
    description: 'Write a clear commit message for the staged changes',
    content: `1. Run \`git diff --cached\`; if nothing is staged, use \`git diff\`.
2. Write a subject line under 60 characters in the imperative mood ("Add", "Fix").
3. Add a short body explaining why the change was made, if it is not obvious.
4. Show the message to the user. Do not commit unless they ask.`,
  },
  {
    name: 'explain-code',
    description: 'Explain how a file or feature works, for a new contributor',
    content: `1. Read the file or feature the user names, and the code it calls.
2. Start with a two-sentence summary of what it does and why.
3. Walk through the main flow in order, naming functions and files.
4. Point out anything surprising: side effects, global state, known limitations.
5. Keep it short; offer to go deeper on any part.`,
  },
];

type Draft = { name: string; description: string; content: string; scope: SkillScope; isNew: boolean };
const SLUG = /^[a-z0-9][a-z0-9-]{0,62}$/;

export default function SkillsView({ onUse }: { onUse: (text: string) => void }) {
  const [skills, setSkills] = useState<Skill[]>([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState('');
  const [selected, setSelected] = useState<Skill | null>(null);
  const [detail, setDetail] = useState<{ description: string; body: string } | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try { setSkills((await api.skills()).skills || []); setError(null); }
    catch { setError('Could not load skills. Is the backend running?'); }
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

  const startNew = (t?: (typeof TEMPLATES)[number]) => {
    setSelected(null);
    setError(null);
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
    } catch (e: any) {
      setError(String(e.message || e).replace(/^\d+\s*/, '').replace(/^\{"detail":"(.*)"\}$/, '$1'));
    } finally { setSaving(false); }
  };

  const remove = async (s: Skill) => {
    if (!confirm(`Delete the skill "${s.name}"? This removes its SKILL.md file.`)) return;
    try { await api.deleteSkill(s.name, s.scope); setSelected(null); await load(); }
    catch (e: any) { setError(`Delete failed: ${e.message || e}`); }
  };

  const addTemplate = async (t: (typeof TEMPLATES)[number]) => {
    try {
      await api.saveSkill({ ...t, scope: 'project' });
      await load();
      setSelected({ name: t.name, scope: 'project', description: t.description });
    } catch (e: any) { setError(`Could not add template: ${e.message || e}`); }
  };

  const missingTemplates = TEMPLATES.filter((t) => !skills.some((s) => s.name === t.name));

  return (
    <div className="skills">
      <aside className="skills-list" aria-label="Skills">
        <div className="skills-head">
          <h2>Skills</h2>
          <button className="btn primary" onClick={() => startNew()}>{I.plus()} New skill</button>
        </div>
        <p className="hint">Reusable instructions for the agent. Type <code>/name</code> in a session to use one.</p>
        <div className="searchfield">
          {I.search()}
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search skills" aria-label="Search skills" />
        </div>
        {loading ? <div className="hint" style={{ padding: 12 }}>Loading…</div> : (
          <ul>
            {shown.map((s) => (
              <li key={s.scope + s.name}>
                <button className={`skillrow ${selected?.name === s.name && selected?.scope === s.scope && !draft ? 'on' : ''}`}
                  onClick={() => { setDraft(null); setError(null); setSelected(s); }}>
                  <span className="skillname">/{s.name}</span>
                  <span className={`scope scope-${s.scope}`}>{s.scope}</span>
                  <span className="skilldesc">{s.description}</span>
                </button>
              </li>
            ))}
            {shown.length === 0 && skills.length > 0 && <li className="hint" style={{ padding: 12 }}>No skills match.</li>}
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
            {draft.isNew && (
              <>
                <label className="f">Start from a template</label>
                <div className="chips">
                  {TEMPLATES.map((t) => <button key={t.name} onClick={() => startNew(t)}>/{t.name}</button>)}
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
        ) : (
          <div className="skills-empty">
            <h3>{skills.length ? 'Pick a skill' : 'Teach Mtrini your workflows'}</h3>
            <p className="hint">Skills are short instruction files the agent follows when you invoke them with <code>/name</code>.
              They live in <code>.mtrini/skills/&lt;name&gt;/SKILL.md</code>, next to your code.</p>
            {missingTemplates.length > 0 && (
              <>
                <label className="f">Starter skills</label>
                <div className="templates">
                  {missingTemplates.map((t) => (
                    <div key={t.name} className="card template">
                      <strong className="mono">/{t.name}</strong>
                      <p className="hint">{t.description}</p>
                      <div className="row">
                        <button className="btn" onClick={() => addTemplate(t)}>{I.plus()} Add</button>
                        <button className="btn" onClick={() => startNew(t)}>Customize</button>
                      </div>
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
        )}
      </section>
    </div>
  );
}
