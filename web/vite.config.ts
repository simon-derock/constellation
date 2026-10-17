import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// dev: the browser sees one origin; /api and /mcp go to the API process
export default defineConfig({
  plugins: [react()],
  server: { proxy: { "/api": "http://localhost:8000", "/mcp": "http://localhost:8000" } },
  test: { environment: "jsdom", setupFiles: ["./src/test-setup.ts"] },
});
