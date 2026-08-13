import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Dev proxy: the Vite server on :5173 forwards /api to the FastAPI app on
// :8000 (run `uvicorn api.app:app --reload`). Production serves both from
// one origin — see api/app.py and Dockerfile.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': { target: 'http://localhost:8000', changeOrigin: true },
    },
  },
});
