import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The sample task is read straight from bench/ at build time (?raw imports).
export default defineConfig({
  plugins: [react()],
  server: { host: "127.0.0.1", port: 5180, strictPort: true, fs: { allow: ["../.."] } },
  build: { chunkSizeWarningLimit: 1500 },
});
