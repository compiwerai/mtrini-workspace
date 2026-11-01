import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import PhoneShell from './mobile/PhoneShell';
import { applySettings, loadSettings } from './lib/settings';
import '@fontsource-variable/dm-sans';
import '@fontsource/ibm-plex-mono/400.css';
import '@fontsource/ibm-plex-mono/500.css';
import './styles.css';

applySettings(loadSettings());

// The Android app (Capacitor) runs the phone shell; `?phone` previews it in a browser.
const isPhone = Boolean((window as any).Capacitor?.isNativePlatform?.()) || new URLSearchParams(location.search).has('phone');

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    {isPhone ? <PhoneShell /> : <App />}
  </React.StrictMode>
);
