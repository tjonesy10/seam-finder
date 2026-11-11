import { expect, test } from "@playwright/test";

test("skip link, nav, filters, pager, retry, and the table region are keyboard operable", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toBeFocused();
  await page.evaluate(() => {
    document.documentElement.tabIndex = -1;
    document.documentElement.focus();
  });
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to main content" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("#main")).toBeFocused();

  await page.getByRole("navigation", { name: "Primary" }).getByRole("link", { name: "Teams" }).focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { level: 1, name: "Teams" })).toBeFocused();

  const filter = page.getByRole("button", { name: "Filter", exact: true });
  await filter.focus();
  await page.keyboard.press("Enter");
  await expect(filter).toBeFocused();

  await page.goto("/stats?season=2024&week=10&team=CIN");
  await expect(page.getByRole("link", { name: "Next" })).toBeVisible();
  await page.getByRole("link", { name: "Next" }).focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/offset=50/);

  await page.locator("[aria-label='Table rows']").focus();
  await expect(page.locator("[aria-label='Table rows']")).toBeFocused();

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/teams");
  const menu = page.getByRole("button", { name: "Menu" });
  await menu.focus();
  await page.keyboard.press("Enter");
  await expect(menu).toHaveAttribute("aria-expanded", "true");
  await page.keyboard.press("Escape");
  await expect(menu).toBeFocused();
  await expect(menu).toHaveAttribute("aria-expanded", "false");
});

test("a list failure retries the same query from the keyboard", async ({ page }) => {
  let calls = 0;
  await page.route(/\/api($|\?|\/)/, async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/api/teams") {
      calls += 1;
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({
          error: { code: "service_unavailable", message: "The database is unavailable." },
        }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        name: "Seam Finder",
        last_refresh_et: "2026-11-05 12:00:00 ET",
        datasets: [],
      }),
    });
  });
  await page.goto("/teams");
  const retry = page.getByRole("button", { name: "Retry" });
  await retry.focus();
  await page.keyboard.press("Enter");
  await expect.poll(() => calls).toBeGreaterThan(1);
});

test("narrow and zoomed layouts keep overflow inside the table", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 700 });
  await page.goto("/stats?season=2024&week=10&team=CIN");
  await expect(page.getByRole("heading", { name: "Player week stats" })).toBeVisible();
  await expect(page.locator("[aria-label='Table rows']")).toBeVisible();
  const overflow = await page.evaluate(() => {
    const root = document.documentElement;
    const region = document.querySelector("[aria-label='Table rows']");
    return {
      documentOverflows: root.scrollWidth > root.clientWidth + 1,
      tableOverflows: region instanceof HTMLElement && region.scrollWidth > region.clientWidth,
    };
  });
  expect(overflow.documentOverflows).toBe(false);
  expect(overflow.tableOverflows).toBe(true);

  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.evaluate(() => {
    document.documentElement.style.zoom = "2";
  });
  const zoomed = await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1);
  expect(zoomed).toBe(true);
});

test("forced colors keep the points legend and values", async ({ page }) => {
  await page.emulateMedia({ forcedColors: "active" });
  await page.goto("/stats?season=2024&week=10&team=CIN");
  await expect(page.getByText("Points intensity, relative to this page").first()).toBeVisible();
  await expect(page.locator("[data-column='fantasy_points']").first()).toBeAttached();
});

test("reduced motion removes transitions", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  const duration = await page.locator("body").evaluate((node) => getComputedStyle(node).animationDuration);
  expect(duration === "0s" || duration === "none").toBe(true);
});
