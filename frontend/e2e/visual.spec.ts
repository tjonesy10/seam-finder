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

test("stats interactions", async ({ page }) => {
  const interactionRows = Array.from({ length: 24 }, (_, index) => ({
    gsis_id: `99-000${String(index).padStart(4, "0")}`,
    player_display_name: `Sample Athlete ${index}`,
    season: 2026,
    week: 1,
    team: index % 2 === 0 ? "XX" : "YY",
    opponent_team: "ZZ",
    position: "WR",
    position_group: "WR",
    fantasy_points: index - 4,
    fantasy_points_ppr: index,
    receiving_yards: index * 3,
  }));
  await page.route(/\/api($|\?|\/)/, async (route) => {
    const url = new URL(route.request().url());
    const body = url.pathname === "/api/player-week-stats"
      ? { data: interactionRows, page: { limit: 50, offset: 0, total: interactionRows.length } }
      : bodyFor(url.pathname);
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
  const sort = encodeURIComponent(JSON.stringify([{ id: "fantasy_points", desc: false }]));
  const filters = encodeURIComponent(
    JSON.stringify({ team: { kind: "multi", values: ["XX"], missing: false } }),
  );
  await page.goto(`/stats?ui_search=Sample&ui_sort=${sort}&ui_filters=${filters}`);
  await settle(page);
  await expect(page.getByText("Search, column filters, multi-sort and export apply to this page only.")).toBeVisible();
  await expect(page.getByRole("button", { name: /Remove Search/ })).toBeVisible();
  await expect(page).toHaveScreenshot("stats-refined.png", { fullPage: true });
  await scan(page);

  await page.getByRole("button", { name: "Columns" }).click();
  await expect(page.getByRole("region", { name: "Columns" })).toBeVisible();
  await expect(page).toHaveScreenshot("stats-columns.png", { fullPage: true });
  await scan(page);

  await page.getByRole("radio", { name: "Compact" }).click();
  await expect(page.locator("[data-density='compact']")).toBeVisible();
  await expect(page).toHaveScreenshot("stats-compact.png", { fullPage: true });
  await scan(page);

  const region = page.locator("[aria-label='Table rows']");
  await region.evaluate((node) => {
    node.scrollTop = 40;
    node.scrollLeft = 220;
  });
  await expect(page).toHaveScreenshot("stats-sticky.png", { fullPage: true });
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
