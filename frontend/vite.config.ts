import { defineConfig } from "vite";

export default defineConfig({
  server: {
    port: 5173,
    proxy: {
      "/ws": {
        target: "ws://127.0.0.1:8000",
        ws: true,
        changeOrigin: true,
      },
      "/health": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
      "/world": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
      "/agents": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
      "/events": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
      "/sim": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
      "/relationships": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
      "/metrics": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
      "/replay": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
