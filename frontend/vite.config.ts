import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: process.env.VITE_API || 'http://localhost:8787', changeOrigin: true }
    }
  },
  build: {
    rollupOptions: {
      // Two apps from one codebase: Mtrini Workspace (index.html) and Mtrini Bots (bots.html).
      input: { main: 'index.html', bots: 'bots.html' }
    }
  },
  test: { environment: 'jsdom', globals: true } as any
});
