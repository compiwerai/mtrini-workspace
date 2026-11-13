import React from 'react';
import { I } from './Icon';

export default function TopBar({ title, project, onOpen, onCommit, diffOpen, onToggleDiff, onExport }: {
  title: string; project: string; onOpen: () => void; onCommit: () => void;
  diffOpen: boolean; onToggleDiff: () => void;
  /** Present on an open session: save it as a shareable HTML page or Markdown. */
  onExport?: (format: 'html' | 'md') => void;
}) {
  const [menu, setMenu] = React.useState(false);
  return (
    <header className="topbar">
      <span className="title">{title || 'New session'}</span>
      {project && <span className="tag">{project}</span>}
      <span className="sp" />
      {onExport && (
        <span className="menuwrap">
          <button className="btn" onClick={() => setMenu((v) => !v)} aria-expanded={menu} aria-haspopup="menu" title="Save this session to share it">{I.download()} Export</button>
          {menu && (
            <span className="popmenu" role="menu" onMouseLeave={() => setMenu(false)}>
              <button role="menuitem" onClick={() => { setMenu(false); onExport('html'); }}>Web page (.html)<small>One file anyone can open</small></button>
              <button role="menuitem" onClick={() => { setMenu(false); onExport('md'); }}>Markdown (.md)<small>For GitHub issues and docs</small></button>
            </span>
          )}
        </span>
      )}
      <button className="btn" onClick={onOpen} title="Reveal project folder">{I.open()} Open</button>
      <button className="btn" onClick={onCommit} title="Commit changes">{I.branch()} Commit</button>
      <button className="btn" onClick={onToggleDiff} title="Toggle changes panel">{I.box()}</button>
    </header>
  );
}
