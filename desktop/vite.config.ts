import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// @tauri-apps/cli docs: start-create-project.md — Vite is the frontend dev server;
// Tauri loads http://localhost:1420 in dev and the built `dist/` in production.
const host = process.env.TAURI_DEV_HOST;

export default defineConfig({
  plugins: [react()],
  // Prevent Vite from obscuring Rust errors.
  clearScreen: false,
  server: {
    port: 1420,
    strictPort: true,
    host: host || false,
    hmr: host
      ? { protocol: "ws", host, port: 1421 }
      : undefined,
    watch: {
      // Tauri works on its own compile cycle; don't watch src-tauri
      // (start-create-project.md step 5).
      ignored: ["**/src-tauri/**"],
    },
  },
  // Produce a clean relative-asset build so Tauri can serve it from tauri://.
  build: {
    target: "es2021",
    minify: !process.env.TAURI_DEBUG ? "esbuild" : false,
    sourcemap: !!process.env.TAURI_DEBUG,
  },
});
