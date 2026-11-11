import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  globalSetup: "./e2e/global-setup.mjs",
  timeout: 60_000,
  use: { baseURL: "http://127.0.0.1:8765" },
  webServer: {
    command: "SERVE_SPA=true python3 -m uvicorn web.main:app --host 127.0.0.1 --port 8765",
    cwd: "..",
    url: "http://127.0.0.1:8765/api/health",
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
