import React from 'react';
import { I } from './Icon';

export default function TopBar({ title, project, onOpen, onCommit, diffOpen, onToggleDiff }: {
  title: string; project: string; onOpen: () => void; onCommit: () => void;
  diffOpen: boolean; onToggleDiff: () => void;
}) {
  return (
    <header className="topbar">
      <span className="title">{title || 'New thread'}</span>
      {project && <span className="tag">{project}</span>}
      <span className="sp" />
      <button className="btn" onClick={onOpen} title="Reveal project folder">{I.open()} Open</button>
      <button className="btn" onClick={onCommit} title="Commit changes">{I.branch()} Commit</button>
      <button className="btn" onClick={onToggleDiff} title="Toggle changes panel">{I.box()}</button>
    </header>
  );
}
