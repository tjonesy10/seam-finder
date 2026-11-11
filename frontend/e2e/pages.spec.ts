import { expect, test } from "@playwright/test";

const ATTRIBUTION =
  "Data: nflverse (nflverse-data), licensed CC BY 4.0. Changes: subset of columns, loaded into a database. Not affiliated with or endorsed by the NFL or nflverse. NFL data belong to their respective owners.";

async function expectAttribution(page: import("@playwright/test").Page) {
  await expect(page.getByText(ATTRIBUTION)).toBeVisible();
  await expect(page.getByRole("link", { name: "nflverse-data" })).toHaveAttribute(
    "href",
    "https://github.com/nflverse/nflverse-data",
  );
  await expect(page.getByRole("link", { name: "CC BY 4.0" })).toHaveAttribute(
    "href",
    "https://creativecommons.org/licenses/by/4.0/",
  );
}

test("home page lists the tables and dataset refreshes", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Seam Finder", level: 1 })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Last refresh per dataset" })).toBeVisible();
  for (const href of ["/teams", "/players", "/games", "/stats", "/load-runs"]) {
    await expect(page.locator(`a[href="${href}"]`)).toBeVisible();
  }
  for (const dataset of ["teams", "players", "games", "player_week_stats"]) {
    await expect(page.getByText(new RegExp(`${dataset}:`))).toBeVisible();
  }
  await expectAttribution(page);
  await expect(page.getByText(/Last refresh: \d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} ET/)).toBeVisible();
  await page.screenshot({ path: "/opt/cursor/artifacts/f009-home.png", fullPage: true });
});

test("table pages show their filters", async ({ page }) => {
  const pages = [
    { path: "/teams", title: "Teams", fields: ["conf", "division"] },
    { path: "/players", title: "Players", fields: ["q", "position", "team", "status"] },
    { path: "/games", title: "Games", fields: ["season", "week", "season_type", "team"] },
    {
      path: "/stats",
      title: "Player week stats",
      fields: ["season", "week", "season_type", "team", "position", "player", "game_id"],
    },
    { path: "/load-runs", title: "Load runs", fields: ["dataset", "status", "season"] },
  ];
  for (const item of pages) {
    await page.goto(item.path);
    await expect(page.getByRole("heading", { name: item.title, level: 1 })).toBeVisible();
    await expect(page.locator("table")).toBeVisible();
    await expect(page.locator("form")).toBeVisible();
    for (const field of item.fields) {
      await expect(page.locator(`input[name="${field}"]`)).toBeVisible();
    }
    await expectAttribution(page);
  }
  await page.screenshot({ path: "/opt/cursor/artifacts/f009-teams.png", fullPage: true });
});

test("stats filter, sort, and paging keep the shared link", async ({ page }) => {
  await page.goto("/stats?season=2024&week=10&team=CIN");
  await expect(page.getByText("Ja'Marr Chase").first()).toBeVisible();
  await page.getByRole("link", { name: "receiving_yards", exact: true }).click();
  await expect(page).toHaveURL(/sort=receiving_yards/);
  await expect(page).toHaveURL(/season=2024/);
  await expect(page).toHaveURL(/week=10/);
  await expect(page).toHaveURL(/team=CIN/);
  await expect(page.getByText("Fictional Player 001").first()).toBeVisible();
  await page.screenshot({ path: "/opt/cursor/artifacts/f009-stats-sorted.png", fullPage: true });
  await page.getByRole("link", { name: "Next" }).click();
  await expect(page).toHaveURL(/offset=50/);
  await expect(page).toHaveURL(/season=2024/);
  await expect(page).toHaveURL(/week=10/);
  await expect(page).toHaveURL(/team=CIN/);
  await expect(page.getByText(/rows 51-100 of /)).toBeVisible();
  await page.screenshot({ path: "/opt/cursor/artifacts/f009-stats-page-2.png", fullPage: true });
});

test("bad parameters and unknown paths stay in the page chrome", async ({ page }) => {
  const response = page.waitForResponse(
    (item) => item.url().includes("/api/games") && item.url().includes("week=abc"),
  );
  await page.goto("/games?week=abc");
  expect((await response).status()).toBe(400);
  await expect(page.getByText("week must be an integer from 1 to 22")).toBeVisible();
  await expect(page.locator("form")).toBeVisible();
  await expect(page.locator("body")).not.toContainText("Traceback");
  await expectAttribution(page);
  await page.screenshot({ path: "/opt/cursor/artifacts/f009-bad-week.png", fullPage: true });

  await page.goto("/not-a-page");
  await expect(page.getByText("Not found")).toBeVisible();
  await expectAttribution(page);
  await page.screenshot({ path: "/opt/cursor/artifacts/f009-not-found.png", fullPage: true });
});

test("pages have no external images", async ({ page }) => {
  for (const path of ["/", "/teams", "/games?week=abc", "/not-a-page"]) {
    await page.goto(path);
    const html = (await page.content()).toLowerCase();
    expect(html).not.toContain("<img");
    expect(html).not.toContain("url(http");
    expect(html).not.toContain("url(//");
  }
});

test("health stays JSON", async ({ request }) => {
  const response = await request.get("/api/health");
  expect(response.status()).toBe(200);
  expect(response.headers()["content-type"]).toContain("application/json");
  const body = await response.json();
  expect(body.status).toBe("ok");
  expect(body.database).toBe("ok");
});

test("attribution stays on screen when GET /api is down", async ({ page }) => {
  await page.route("**/api", async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname !== "/api") {
      await route.continue();
      return;
    }
    await route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({
        error: { code: "service_unavailable", message: "The database is unavailable." },
      }),
    });
  });
  await page.goto("/");
  await expect(page.getByText("The database is unavailable.")).toBeVisible();
  await expect(page.getByText("Last refresh: none")).toBeVisible();
  await expectAttribution(page);
  await page.screenshot({ path: "/opt/cursor/artifacts/f009-api-down.png", fullPage: true });
});
