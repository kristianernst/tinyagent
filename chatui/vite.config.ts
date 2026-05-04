import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const TINYAGENT_API = process.env.TINYAGENT_API ?? "http://127.0.0.1:8765";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: TINYAGENT_API,
        changeOrigin: true,
      },
    },
  },
});
