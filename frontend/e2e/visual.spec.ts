import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { bodyFor, emptyStats, meta, unavailable } from "./synthetic";

const FROZEN = new Date("2026-11-10T17:00:00.000Z");

async function installApi(page: Page) {
  await page.route(/\/api($|\?|\/)/, async (route) => {
    const url = new URL(route.request().url());
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(bodyFor(url.pathname)),
    });
  });
}

async function settle(page: Page) {
  await page.evaluate(() => document.fonts.ready);
}

async function scan(page: Page) {
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  expect(results.violations).toEqual([]);
}

test.beforeEach(async ({ page }) => {
  await page.clock.install({ time: FROZEN });
});

test("routes", async ({ page }) => {
  await installApi(page);
  for (const path of ["/", "/teams", "/players", "/games", "/stats", "/load-runs"]) {
    await page.goto(path);
    await settle(page);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
    await expect(page.getByText(/Data: nflverse/)).toBeVisible();
    await expect(page).toHaveScreenshot(`${path === "/" ? "home" : path.slice(1)}.png`, {
      fullPage: true,
    });
    await scan(page);
  }
});

test("stats loading", async ({ page }) => {
  let release: () => void = () => undefined;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route(/\/api($|\?|\/)/, async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/player-week-stats") {
      await gate;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify(bodyFor(url.pathname)),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(bodyFor(url.pathname)),
    });
  });
  await page.goto("/stats");
  await settle(page);
  await expect(page.getByText("Loading data")).toBeVisible();
  await expect(page).toHaveScreenshot("stats-loading.png", { fullPage: true });
  await scan(page);
  release();
});

test("stats empty", async ({ page }) => {
  await page.route(/\/api($|\?|\/)/, async (route) => {
    const url = new URL(route.request().url());
    const body = url.pathname === "/api/player-week-stats" ? emptyStats : bodyFor(url.pathname);
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
  await page.goto("/stats");
  await settle(page);
  await expect(page.getByText(/No results for these filters/)).toBeVisible();
  await expect(page).toHaveScreenshot("stats-empty.png", { fullPage: true });
  await scan(page);
});

test("stats unavailable", async ({ page }) => {
  await page.route(/\/api($|\?|\/)/, async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/player-week-stats") {
      await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify(unavailable) });
      return;
    }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(meta) });
  });
  await page.goto("/stats");
  await settle(page);
  await expect(page.getByText("The database is unavailable.")).toBeVisible();
  await expect(page).toHaveScreenshot("stats-unavailable.png", { fullPage: true });
  await scan(page);
});

test("home metadata outage", async ({ page }) => {
  await page.route(/\/api($|\?|\/)/, async (route) => {
    await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify(unavailable) });
  });
  await page.goto("/");
  await settle(page);
  await expect(page.getByText("Last refresh: none")).toBeVisible();
  await expect(page).toHaveScreenshot("home-outage.png", { fullPage: true });
  await scan(page);
});

test("not found", async ({ page }) => {
  await installApi(page);
  await page.goto("/not-a-page");
  await settle(page);
  await expect(page.getByText("Not found")).toBeVisible();
  await expect(page).toHaveScreenshot("not-found.png", { fullPage: true });
  await scan(page);
});
