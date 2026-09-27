import { defineConfig } from 'vite';
import { resolve } from 'path';

// Build the same dashboard that the Python backend serves.
export default defineConfig({
  build: {
    rollupOptions: {
      input: {
        main: resolve(__dirname, 'index.html'),
        dashboard: resolve(__dirname, 'backend/static/dashboard.html'),
      },
    },
  },
});
