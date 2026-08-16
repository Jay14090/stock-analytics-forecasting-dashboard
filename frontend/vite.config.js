import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // Proxy /api to Flask in development so the browser sees one origin and
    // CORS never enters the picture locally.
    proxy: {
      '/api': {
        target: process.env.VITE_API_TARGET || 'http://127.0.0.1:5000',
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
    // Plotly is ~1.2MB even as the finance-only bundle, which is the floor for
    // a charting library of this class. It is split into its own chunk so it
    // loads in parallel with — and is cached independently of — app code.
    chunkSizeWarningLimit: 1300,
    rollupOptions: {
      output: {
        manualChunks: {
          plotly: ['plotly.js-finance-dist-min'],
          vendor: ['react', 'react-dom', 'react-router-dom'],
        },
      },
    },
  },
});
