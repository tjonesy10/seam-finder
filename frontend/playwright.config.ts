import { defineConfig, devices } from "@playwright/test";

const screenshot = {
  animations: "disabled" as const,
  caret: "hide" as const,
  fullPage: true,
  maxDiffPixels: 100,
  threshold: 0.2,
};

const visualUse = {
  ...devices["Desktop Chrome"],
  baseURL: "http://127.0.0.1:8765",
  colorScheme: "dark" as const,
  deviceScaleFactor: 1,
  locale: "en-US",
  reducedMotion: "reduce" as const,
  timezoneId: "America/New_York",
};

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { toHaveScreenshot: screenshot },
  globalSetup: "./e2e/global-setup.mjs",
  webServer: {
    command: "alembic upgrade head && SERVE_SPA=true python3 -m uvicorn web.main:app --host 127.0.0.1 --port 8765",
    cwd: "..",
    url: "http://127.0.0.1:8765/api/health",
    reuseExistingServer: false,
    timeout: 120_000,
  },
  projects: [
    {
      name: "integration",
      testMatch: /(?:pages|keyboard)\.spec\.ts/,
      use: { baseURL: "http://127.0.0.1:8765" },
    },
    {
      name: "visual-desktop",
      testMatch: /visual\.spec\.ts/,
      use: { ...visualUse, viewport: { width: 1440, height: 1000 } },
    },
    {
      name: "visual-mobile",
      testMatch: /visual\.spec\.ts/,
      use: { ...visualUse, viewport: { width: 390, height: 844 } },
    },
  ],
});
