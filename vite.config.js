import { defineConfig } from 'vite';
import { resolve } from 'path';

// The landing page links to the root dashboard, which connects to Railway directly.
export default defineConfig({
  build: {
    rollupOptions: {
      input: {
        main: resolve(__dirname, 'index.html'),
        dashboard: resolve(__dirname, 'dashboard.html'),
      },
    },
  },
});
