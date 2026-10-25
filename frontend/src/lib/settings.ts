export type UISettings = {
  theme: 'glass' | 'dark' | 'light' | 'system';
  accent: 'teal' | 'blue' | 'green' | 'violet' | 'amber';
  density: 'comfortable' | 'compact';
  editorFontSize: number;
  minimap: boolean;
  wordWrap: boolean;
  terminalFontSize: number;
  permissionMode: 'ask' | 'auto' | 'readonly' | 'plan';
  uiFontSize: number;
  contentWidth: 'normal' | 'wide';
  motion: 'system' | 'reduce';
  showChanges: boolean;
  sendKey: 'enter' | 'mod-enter';
  defaultEffort: 'off' | 'low' | 'medium' | 'high' | 'xhigh' | 'max';
  toolsExpanded: boolean;
  showStarters: boolean;
  confirmDelete: boolean;
  useSkills: boolean;
  useInstructions: boolean;
};

const KEY = 'mtrini.ui';

export const DEFAULTS: UISettings = {
  theme: 'light',
  accent: 'teal',
  density: 'comfortable',
  editorFontSize: 13,
  minimap: false,
  wordWrap: false,
  terminalFontSize: 12,
  permissionMode: 'ask',
  uiFontSize: 14,
  contentWidth: 'normal',
  motion: 'system',
  showChanges: true,
  sendKey: 'enter',
  defaultEffort: 'off',
  toolsExpanded: false,
  showStarters: true,
  confirmDelete: true,
  useSkills: true,
  useInstructions: true,
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
  root.dataset.width = s.contentWidth;
  root.dataset.motion = s.motion;
  root.style.setProperty('--ui-size', `${s.uiFontSize}px`);
}

export function saveSettings(patch: Partial<UISettings>): UISettings {
  const next = { ...loadSettings(), ...patch };
  localStorage.setItem(KEY, JSON.stringify(next));
  applySettings(next);
  window.dispatchEvent(new Event('mtrini:ui-changed'));
  return next;
}
