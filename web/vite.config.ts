import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// En développement (`npm run dev`), l'API vient de `research-lab serve` (port 8765).
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://127.0.0.1:8765" } },
});
