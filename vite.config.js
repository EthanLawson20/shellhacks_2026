import { defineConfig } from 'vite';
import { resolve } from 'path';

// without this vite only builds index.html and the dashboard never makes it into dist/
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