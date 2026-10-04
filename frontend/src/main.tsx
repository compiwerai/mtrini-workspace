import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import { applySettings, loadSettings } from './lib/settings';
import './styles.css';

applySettings(loadSettings());

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
