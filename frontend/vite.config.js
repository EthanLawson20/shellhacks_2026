import { defineConfig } from 'vite';
import { resolve } from 'path';

// The landing page links to the root dashboard, which connects to Railway directly.
export default defineConfig({
  // Serve and copy the shared repo-level image assets into the frontend build.
  publicDir: resolve(__dirname, '../images'),
  build: {
    rollupOptions: {
      input: {
        main: resolve(__dirname, 'index.html'),
        dashboard: resolve(__dirname, 'dashboard.html'),
      },
    },
  },
});
