export type UISettings = {
  theme: 'glass' | 'dark' | 'light' | 'system';
  accent: 'teal' | 'blue' | 'green' | 'violet' | 'amber';
  density: 'comfortable' | 'compact';
  editorFontSize: number;
  minimap: boolean;
  wordWrap: boolean;
  terminalFontSize: number;
  permissionMode: 'ask' | 'auto' | 'readonly';
};

const KEY = 'mtrini.ui';

export const DEFAULTS: UISettings = {
  theme: 'glass',
  accent: 'teal',
  density: 'comfortable',
  editorFontSize: 13,
  minimap: false,
  wordWrap: false,
  terminalFontSize: 12,
  permissionMode: 'ask',
};

export function loadSettings(): UISettings {
  try {
    const raw = JSON.parse(localStorage.getItem(KEY) || '{}');
    return { ...DEFAULTS, ...raw };
  } catch {
    return { ...DEFAULTS };
  }
}

export function applySettings(s: UISettings) {
  const root = document.documentElement;
  let theme = s.theme;
  if (theme === 'system') {
    theme = window.matchMedia?.('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
  }
  root.dataset.theme = theme;
  root.dataset.accent = s.accent;
  root.dataset.density = s.density;
}

export function saveSettings(patch: Partial<UISettings>): UISettings {
  const next = { ...loadSettings(), ...patch };
  localStorage.setItem(KEY, JSON.stringify(next));
  applySettings(next);
  window.dispatchEvent(new Event('mtrini:ui-changed'));
  return next;
}
