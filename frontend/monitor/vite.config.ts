import path from "path"
import tailwindcss from "@tailwindcss/vite"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"

// Build output is the packaged Python resource served by monitoring_web.py at `/` and `/assets/*`.
// Content-hashed names keep the tracked output deterministic for the CI drift check.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: "/",
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
  build: {
    outDir: path.resolve(__dirname, "../../src/codex_harness/resources/observatory"),
    emptyOutDir: true,
    assetsDir: "assets",
    sourcemap: false,
    modulePreload: { polyfill: false },
    reportCompressedSize: false,
  },
})
