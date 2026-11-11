import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "./App";
import { ATTRIBUTION_TEXT } from "./attribution";
import { memoryHistory } from "./router";
import { stats } from "./resources";

const META = {
  name: "Seam Finder",
  attribution: { text: "API-ATTRIBUTION-SHOULD-NOT-RENDER", links: [] },
  endpoints: ["/api/player-week-stats"],
  last_refresh_et: "2026-11-05 12:00:00 ET",
  datasets: [{ dataset: "player_week_stats", finished_at: "2026-11-05 12:00:00 ET" }],
};

const pageOne = [
  {
    gsis_id: "B",
    player_display_name: "Beta Sample",
    season: 2026,
    week: 1,
    team: "YY",
    opponent_team: "ZZ",
    position: "WR",
    position_group: "WR",
    fantasy_points: 1,
    fantasy_points_ppr: null,
    receiving_yards: 10,
    target_share: 0.2,
  },
  {
    gsis_id: "A",
    player_display_name: "Alpha Sample",
    season: 2026,
    week: 1,
    team: "xx",
    opponent_team: "ZZ",
    position: "QB",
    position_group: "QB",
    fantasy_points: 1,
    fantasy_points_ppr: -2.5,
    receiving_yards: null,
    target_share: null,
  },
  {
    gsis_id: "C",
    player_display_name: "Hidden Marker",
    season: 2026,
    week: 2,
    team: null,
    opponent_team: "ZZ",
    position: "WR",
    position_group: "WR",
    fantasy_points: -4,
    fantasy_points_ppr: 4,
    receiving_yards: 2,
    target_share: 0,
  },
];

const pageTwo = [
  {
    gsis_id: "E",
    player_display_name: "Echo",
    season: 2026,
    week: 3,
    team: "QQ",
    opponent_team: "ZZ",
    position: "RB",
    position_group: "RB",
    fantasy_points: 8,
    fantasy_points_ppr: 8,
    receiving_yards: 1,
    target_share: 0.1,
  },
];

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

function installStats() {
  const urls: string[] = [];
  vi.stubGlobal("fetch", (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    urls.push(url);
    if (url.includes("/api/player-week-stats")) {
      const offset = new URL(url, "http://local").searchParams.get("offset");
      const data = offset === "50" ? pageTwo : pageOne;
      return Promise.resolve(json({ data, page: { limit: 50, offset: Number(offset ?? 0), total: 51 } }));
    }
    return Promise.resolve(json(META));
  });
  return urls;
}

function rowIds(): string[] {
  return [...document.querySelectorAll("[data-row-id]")].map((node) => node.getAttribute("data-row-id") ?? "");
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("premium table page", () => {
  it("keeps dataset paging separate from this page and does not fetch ui state", async () => {
    const urls = installStats();
    const history = memoryHistory("/stats?season=2026");
    render(<App history={history} />);
    expect(await screen.findByText("Beta Sample")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "This page" })).toBeTruthy();
    expect(screen.getByText("Search, column filters, multi-sort and export apply to this page only.")).toBeTruthy();
    expect(screen.getByText("Showing 3 of 3 loaded rows")).toBeTruthy();
    expect(screen.getByText("rows 1-3 of 51")).toBeTruthy();
    expect(document.body.textContent).toContain(ATTRIBUTION_TEXT);
    expect(document.body.textContent?.toLowerCase()).not.toContain("salary");
    expect(document.body.textContent).not.toContain("RotoGuru");
    expect(document.body.textContent).not.toContain("dk_points");
    expect(screen.getAllByText("Points intensity, relative to this page").length).toBeGreaterThan(0);
    expect(screen.getAllByText("1.00").length).toBeGreaterThan(0);
    expect(screen.getByText("20.0%")).toBeTruthy();
    expect(screen.getAllByLabelText("Missing").length).toBeGreaterThan(0);
    const listUrls = () => urls.filter((url) => url.includes("/api/player-week-stats"));
    expect(listUrls().every((url) => !url.includes("ui_"))).toBe(true);
    const before = listUrls().length;
    fireEvent.click(screen.getByRole("button", { name: "Sort by Standard scoring" }));
    expect(await screen.findByText("Page sort: 1. Standard scoring ascending")).toBeTruthy();
    expect(rowIds()[0]).toBe("C-2026-2");
    expect(listUrls().length).toBe(before);
    expect(history.location.search).toContain("ui_sort=");
    expect(history.location.search).toContain("season=2026");
    fireEvent.click(screen.getByRole("button", { name: /Sort by Standard scoring 1↑, priority 1 ascending/ }));
    expect(await screen.findByText("Page sort: 1. Standard scoring descending")).toBeTruthy();
    expect(rowIds().slice(0, 2)).toEqual(["A-2026-1", "B-2026-1"]);
    fireEvent.click(screen.getByRole("button", { name: "Sort by Week" }), { shiftKey: true });
    expect(await screen.findByText(/2\. Week ascending/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Sort" }));
    fireEvent.click(screen.getByRole("button", { name: "Add sort" }));
    expect(await screen.findByText(/A fourth sort cannot be added/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Add sort" }).hasAttribute("disabled")).toBe(true);
    expect(listUrls().length).toBe(before);
  });

  it("filters the loaded page, keeps a missing selection removable, and clears only page filters", async () => {
    installStats();
    const history = memoryHistory("/stats");
    render(<App history={history} />);
    expect(await screen.findByText("Beta Sample")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Column filter for Standard scoring" }));
    fireEvent.change(screen.getByLabelText("Minimum"), { target: { value: "5" } });
    fireEvent.change(screen.getByLabelText("Maximum"), { target: { value: "1" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(screen.getByText(/Min cannot be greater than max/)).toBeTruthy();
    expect(rowIds()).toHaveLength(3);
    fireEvent.change(screen.getByLabelText("Minimum"), { target: { value: "1" } });
    fireEvent.change(screen.getByLabelText("Maximum"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(await screen.findByText("Showing 2 of 3 loaded rows")).toBeTruthy();
    expect(rowIds()).toEqual(["B-2026-1", "A-2026-1"]);
    fireEvent.click(screen.getByRole("button", { name: "Column filter for Team" }));
    fireEvent.click(screen.getByLabelText("XX"));
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(await screen.findByText("Showing 1 of 3 loaded rows")).toBeTruthy();
    expect(rowIds()).toEqual(["A-2026-1"]);
    fireEvent.click(screen.getByRole("button", { name: "Columns" }));
    fireEvent.click(screen.getByRole("checkbox", { name: /Player display name/ }));
    await waitFor(() => expect(screen.queryByText("Alpha Sample")).toBeNull());
    fireEvent.change(screen.getByLabelText("Search this page"), { target: { value: "Alpha" } });
    fireEvent.keyDown(screen.getByLabelText("Search this page"), { key: "Enter" });
    expect(await screen.findByRole("button", { name: /Remove Search/ })).toBeTruthy();
    expect(rowIds()).toEqual(["A-2026-1"]);
    fireEvent.click(screen.getByRole("link", { name: "Next" }));
    expect(await screen.findByText("No rows match on this page.")).toBeTruthy();
    expect(screen.getByRole("button", { name: /Remove Search/ })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Previous" })).toBeTruthy();
    expect(history.location.search).toContain("offset=50");
    fireEvent.click(screen.getByRole("button", { name: "Clear page filters" }));
    expect(await screen.findByText("Showing 1 of 1 loaded rows")).toBeTruthy();
    expect(rowIds()).toEqual(["E-2026-3"]);
    expect(history.location.search).toContain("offset=50");
    expect(history.location.search).not.toContain("ui_search");
  });

  it("restores sort, width, and density from the URL and from back", async () => {
    installStats();
    const history = memoryHistory(
      `/stats?ui_density=compact&ui_widths=${encodeURIComponent(JSON.stringify({ player_display_name: 320 }))}&ui_sort=${encodeURIComponent(JSON.stringify([{ id: "fantasy_points", desc: false }]))}`,
    );
    render(<App history={history} />);
    expect(await screen.findByText("Beta Sample")).toBeTruthy();
    expect(document.querySelector("[data-density='compact']")).not.toBeNull();
    expect(document.querySelector("[aria-label='Resize Player display name']")?.getAttribute("aria-valuenow")).toBe("320");
    expect(rowIds()[0]).toBe("C-2026-2");
    fireEvent.click(screen.getByRole("radio", { name: "Comfortable" }));
    expect(await screen.findByRole("radio", { name: "Comfortable", checked: true })).toBeTruthy();
    await act(async () => {
      history.back();
    });
    expect(document.querySelector("[data-density='compact']")).not.toBeNull();
  });

  it("exports the filtered logical rows and refuses stale or empty lists", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-11-10T17:00:00.000Z"));
    const blobs: Blob[] = [];
    vi.spyOn(URL, "createObjectURL").mockImplementation((blob) => {
      blobs.push(blob as Blob);
      return "blob:page";
    });
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
    let download = "";
    const click = HTMLAnchorElement.prototype.click;
    HTMLAnchorElement.prototype.click = function clickDownload() {
      download = this.download;
    };
    installStats();
    render(<App history={memoryHistory("/stats?ui_hidden=%5B%22team%22%5D")} />);
    expect(await screen.findByText("Beta Sample")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Sort by Standard scoring" }));
    expect(await screen.findByText("Page sort: 1. Standard scoring ascending")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Export this page CSV \(3\)/ }));
    const text = await blobs[0].text();
    expect(download).toBe("seam-finder-stats-20261110-120000-ET.csv");
    expect(text.startsWith("player_display_name,")).toBe(true);
    expect(text).not.toContain("\nteam,");
    expect(text.split("\r\n")[1]?.startsWith("Hidden Marker,")).toBe(true);
    expect(text).not.toContain("nflverse");
    HTMLAnchorElement.prototype.click = click;
    vi.useRealTimers();
    expect(stats.columns[0]).toBe("player_display_name");
  });

  it("disables export when the list fails and keeps attribution", async () => {
    vi.stubGlobal("fetch", (input: RequestInfo | URL) => {
      const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
      if (url.includes("/api/player-week-stats")) {
        return Promise.resolve(json({ error: { message: "The database is unavailable." } }, 503));
      }
      return Promise.resolve(json(META));
    });
    render(<App history={memoryHistory("/stats")} />);
    expect(await screen.findByText("The database is unavailable.")).toBeTruthy();
    const button = screen.getByRole("button", { name: /Export this page CSV/ });
    expect((button as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText("Export is unavailable because the list failed.")).toBeTruthy();
    expect(document.body.textContent).toContain(ATTRIBUTION_TEXT);
    expect(document.body.textContent).not.toContain("RotoGuru");
  });
});
