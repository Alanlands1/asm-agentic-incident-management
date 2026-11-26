import path from "node:path";
import { defineConfig, devices } from "@playwright/test";

// Browser tests against the real console and backend, on a throwaway SQLite database seeded with the sample tickets.
// The model, Jira and Confluence are switched off: nothing leaves the machine and nothing costs money.
const DB = path.resolve(__dirname, "e2e", ".data", "e2e.db");
const PYTHON = process.env.PYTHON ?? "python";
const API = "http://127.0.0.1:8100/api/v1";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false, // one shared database
  workers: 1,
  reporter: [["list"], ["html", { open: "never" }]],
  use: { baseURL: "http://127.0.0.1:3100", trace: "retain-on-failure", ...devices["Desktop Chrome"] },
  webServer: [
    {
      command: `${PYTHON} scripts/seed_e2e.py "${DB}" && ${PYTHON} -m uvicorn app.main:app --port 8100`,
      cwd: path.resolve(__dirname, "..", "backend"),
      url: `${API}/health`,
      timeout: 180_000,
      reuseExistingServer: false,
      env: {
        DATABASE_URL: `sqlite+aiosqlite:///${DB.replace(/\\/g, "/")}`,
        LLM_ENABLED: "false",
        ANTHROPIC_API_KEY: "",
        JIRA_WRITE_BACK: "false",
        SLA_AUTO_WARN: "false",
        JIRA_SYNC_MINUTES: "0",
        CONFLUENCE_SYNC_MINUTES: "0",
        CONFLUENCE_WRITE_BACK: "false",
        ATLASSIAN_BASE_URL: "",
        ATLASSIAN_EMAIL: "",
        ATLASSIAN_API_TOKEN: "",
        ATLASSIAN_OAUTH_CLIENT_ID: "",
        ATLASSIAN_OAUTH_CLIENT_SECRET: "",
        PHOENIX_ENABLED: "false",
      },
    },
    {
      // A production build: every page compiled up front, as users get it (the dev server compiles each on first visit).
      command: "npx next build && npx next start --port 3100",
      url: "http://127.0.0.1:3100",
      timeout: 300_000,
      reuseExistingServer: false,
      env: { BACKEND_INTERNAL_URL: API },
    },
  ],
});
