import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

// Unit tests for console components: jsdom, the same `@/` alias as the app. Browser tests live in e2e/ (Playwright).
export default defineConfig({
  esbuild: { jsx: "automatic" },
  resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
