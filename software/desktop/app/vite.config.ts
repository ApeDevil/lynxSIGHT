import { svelte } from "@sveltejs/vite-plugin-svelte";
import { defineConfig } from "vitest/config";

// Tauri serves the built files (src-tauri/tauri.conf.json); `npm run dev` on port 1420.
export default defineConfig({
  plugins: [svelte()],
  clearScreen: false,
  server: { port: 1420, strictPort: true },
  build: { target: "es2022" },
  test: { environment: "jsdom", include: ["src/**/*.test.ts"] },
  // Svelte's client build for component tests (vitest sets the mode to "test").
  resolve: { conditions: ["browser"] },
});
