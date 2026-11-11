import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { ATTRIBUTION_LINKS, ATTRIBUTION_TEXT } from "./attribution";
import { memoryHistory } from "./router";

const META = {
  name: "Seam Finder",
  attribution: { text: "API-ATTRIBUTION-SHOULD-NOT-RENDER", links: [] },
  endpoints: ["/api/teams"],
  last_refresh_et: "2026-11-05 12:00:00 ET",
  datasets: [
    { dataset: "teams", finished_at: "2026-11-05 12:00:00 ET" },
    { dataset: "players", finished_at: "2026-11-05 12:00:00 ET" },
    { dataset: "games", finished_at: "2026-11-05 12:00:00 ET" },
    { dataset: "player_week_stats", finished_at: "none" },
  ],
};

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function installFetch(handler: (url: string) => Response | Promise<Response>) {
  vi.stubGlobal("fetch", (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    return Promise.resolve(handler(url));
  });
}

function renderAt(path: string) {
  return render(<App history={memoryHistory(path)} />);
}

function expectAttribution() {
  expect(document.body.textContent).toContain(ATTRIBUTION_TEXT);
  for (const link of ATTRIBUTION_LINKS) {
    const anchor = screen.getByRole("link", { name: link.label });
    expect(anchor.getAttribute("href")).toBe(link.url);
  }
  expect(document.body.textContent).not.toContain("API-ATTRIBUTION-SHOULD-NOT-RENDER");
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("shell attribution", () => {
  it("shows the static attribution while the API request is still pending", async () => {
    vi.stubGlobal("fetch", () => new Promise(() => undefined));
    renderAt("/");
    expect(await screen.findByText(ATTRIBUTION_TEXT)).toBeTruthy();
    expectAttribution();
    expect(document.body.textContent).toContain("Last refresh: none");
  });

  it("shows the attribution and the database message when GET /api is 503", async () => {
    installFetch(() => json({ error: { code: "service_unavailable", message: "hidden" } }, 503));
    renderAt("/");
    expect(await screen.findByText("The database is unavailable.")).toBeTruthy();
    expectAttribution();
    expect(document.body.textContent).toContain("Last refresh: none");
  });

  it("shows the attribution and the generic message when GET /api is another 5xx", async () => {
    installFetch(() => json({ error: { message: "hidden" } }, 500));
    renderAt("/");
    expect(await screen.findByText("Something went wrong.")).toBeTruthy();
    expectAttribution();
    expect(document.body.textContent).toContain("Last refresh: none");
  });

  it("shows the attribution and the generic message when the network fails", async () => {
    vi.stubGlobal("fetch", () => Promise.reject(new TypeError("offline")));
    renderAt("/");
    expect(await screen.findByText("Something went wrong.")).toBeTruthy();
    expectAttribution();
    expect(document.body.textContent).toContain("Last refresh: none");
  });

  it("shows the attribution on the not-found view before a successful API response is required", async () => {
    vi.stubGlobal("fetch", () => new Promise(() => undefined));
    renderAt("/not-a-page");
    expect(await screen.findByText("Not found")).toBeTruthy();
    expectAttribution();
    expect(document.body.textContent).toContain("Last refresh: none");
  });

  it("shows the bad-parameter message and keeps the filter form", async () => {
    installFetch((url) => {
      if (url.includes("/api/games")) {
        return json(
          { error: { code: "invalid_parameter", message: "week must be an integer from 1 to 22", param: "week" } },
          400,
        );
      }
      return json(META);
    });
    renderAt("/games?week=abc");
    expect(await screen.findByText("week must be an integer from 1 to 22")).toBeTruthy();
    expect(document.querySelector("form")).not.toBeNull();
    expect(document.querySelector('input[name="week"]')).not.toBeNull();
    expect(document.querySelector('input[name="season"]')).not.toBeNull();
    expect(document.body.textContent).not.toContain("Traceback");
    expectAttribution();
    expect(document.body.textContent).toContain("Last refresh: 2026-11-05 12:00:00 ET");
  });

  it("renders the home page from datasets and last_refresh_et", async () => {
    installFetch(() => json(META));
    renderAt("/");
    expect(await screen.findByRole("heading", { name: "Seam Finder" })).toBeTruthy();
    expect(await screen.findByText("teams: 2026-11-05 12:00:00 ET")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Last refresh per dataset" })).toBeTruthy();
    for (const href of ["/teams", "/players", "/games", "/stats", "/load-runs"]) {
      expect(document.querySelector(`a[href="${href}"]`)).not.toBeNull();
    }
    expect(document.body.textContent).toContain("player_week_stats: none");
    expect(document.body.textContent).toContain("Last refresh: 2026-11-05 12:00:00 ET");
    expectAttribution();
    expect(document.body.innerHTML.toLowerCase()).not.toContain("<img");
    expect(document.body.innerHTML).not.toContain("url(http");
    expect(document.body.innerHTML).not.toContain("url(//");
  });

  it("navigates to a table route through the router", async () => {
    installFetch((url) => {
      if (url.includes("/api/teams")) {
        return json({ data: [], page: { limit: 50, offset: 0, total: 0 } });
      }
      return json(META);
    });
    renderAt("/");
    await screen.findByText("teams: 2026-11-05 12:00:00 ET");
    fireEvent.click(within(screen.getByRole("main")).getByRole("link", { name: "Teams" }));
    expect(await screen.findByRole("heading", { name: "Teams" })).toBeTruthy();
    expect(await screen.findByText("rows 0-0 of 0")).toBeTruthy();
  });

  it("renders a table from TanStack Query", async () => {
    installFetch((url) => {
      if (url.includes("/api/teams")) {
        return json({
          data: [{ team_abbr: "CIN", team_name: "Bengals" }],
          page: { limit: 50, offset: 0, total: 1 },
        });
      }
      return json(META);
    });
    renderAt("/teams");
    expect(await screen.findByRole("heading", { name: "Teams" })).toBeTruthy();
    expect(await screen.findByText("CIN")).toBeTruthy();
    expect(document.querySelector('input[name="conf"]')).not.toBeNull();
    expect(document.querySelector('input[name="division"]')).not.toBeNull();
    expect(document.querySelector("table")).not.toBeNull();
    expect(document.body.textContent).toContain("rows 1-1 of 1");
    expectAttribution();
  });

  it("shows a skeleton while the list is loading and an empty state after zero rows", async () => {
    vi.stubGlobal("fetch", () => new Promise(() => undefined));
    renderAt("/teams");
    expect(await screen.findByText("Loading data")).toBeTruthy();
    expect(document.querySelectorAll("table[aria-hidden='true'] tr")).toHaveLength(8);
    expect(document.body.textContent).not.toContain("rows 0-0 of 0");
  });

  it("distinguishes no results from a page past the end", async () => {
    installFetch((url) => {
      if (url.includes("/api/teams")) {
        const offset = new URL(url, "http://local").searchParams.get("offset");
        if (offset === "50") {
          return json({ data: [], page: { limit: 50, offset: 50, total: 1 } });
        }
        return json({ data: [], page: { limit: 50, offset: 0, total: 0 } });
      }
      return json(META);
    });
    renderAt("/teams");
    expect(await screen.findByText(/No results for these filters/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Clear filters" })).toBeTruthy();
    expect(document.body.textContent).toContain("rows 0-0 of 0");
    cleanup();
    renderAt("/teams?offset=50");
    expect(await screen.findByText("No rows on this page.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "First page" })).toBeTruthy();
  });

  it("shows a retry alert for a list failure without a traceback", async () => {
    let calls = 0;
    installFetch((url) => {
      if (url.includes("/api/teams")) {
        calls += 1;
        return json({ error: { code: "service_unavailable", message: "The database is unavailable." } }, 503);
      }
      return json(META);
    });
    renderAt("/teams");
    expect((await screen.findByRole("alert")).textContent).toContain("The database is unavailable.");
    expect(document.body.textContent).not.toContain("Traceback");
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await screen.findByRole("alert");
    expect(calls).toBeGreaterThan(1);
  });
});
