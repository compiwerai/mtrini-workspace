import type { CapacitorConfig } from '@capacitor/cli';

// The Android app: the same interface as the desktop (dist/), started in phone mode (src/mobile/PhoneShell.tsx).
const config: CapacitorConfig = {
  appId: 'ai.compiwer.mtrini',
  appName: 'Mtrini',
  webDir: 'dist',
  android: {
    allowMixedContent: false,
  },
  server: {
    androidScheme: 'https',
  },
};

export default config;
