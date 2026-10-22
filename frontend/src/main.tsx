import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import { applySettings, loadSettings } from './lib/settings';
import '@fontsource-variable/dm-sans';
import '@fontsource/ibm-plex-mono/400.css';
import '@fontsource/ibm-plex-mono/500.css';
import './styles.css';

applySettings(loadSettings());

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
