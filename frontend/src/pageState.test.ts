import { describe, expect, it } from "vitest";
import { datasetQuery, listRequest, normalizeTableSearch, readTableState, stableStringify, writeTableState } from "./pageState";
import { games, players, stats, teams } from "./resources";

describe("table search state", () => {
  it("keeps valid dataset and page state and omits defaults", () => {
    const raw = {
      season: "2024",
      week: "10",
      team: "cin",
      sort: "receiving_yards",
      order: "asc",
      limit: "100",
      offset: "50",
      ui_sort: stableStringify([
        { id: "week", desc: false },
        { id: "fantasy_points", desc: true },
      ]),
      ui_filters: stableStringify({
        team: { kind: "multi", values: ["yy", "xx"], missing: false },
        fantasy_points: { kind: "range", min: -2, max: 10 },
        player_display_name: { kind: "text", value: " Alpha " },
      }),
      ui_search: " sample ",
      ui_hidden: stableStringify(["season", "week"]),
      ui_widths: stableStringify({ player_display_name: 320 }),
      ui_density: "compact",
    };
    const state = readTableState(raw, stats);
    expect(state.filters).toEqual({ season: "2024", week: "10", team: "CIN" });
    expect(state.sort).toBe("receiving_yards");
    expect(state.order).toBe("asc");
    expect(state.limit).toBe(100);
    expect(state.offset).toBe(50);
    expect(state.ui.sort).toEqual([
      { id: "week", desc: false },
      { id: "fantasy_points", desc: true },
    ]);
    expect(state.ui.filters.team).toEqual({ kind: "multi", values: ["XX", "YY"], missing: false });
    expect(state.ui.filters.fantasy_points).toEqual({ kind: "range", min: -2, max: 10 });
    expect(state.ui.filters.player_display_name).toEqual({ kind: "text", value: "Alpha" });
    expect(state.ui.search).toBe("sample");
    expect(state.ui.hidden).toEqual(["season", "week"]);
    expect(state.ui.widths).toEqual({ player_display_name: 320 });
    expect(state.ui.density).toBe("compact");
    const written = writeTableState(state, stats);
    expect(written.ui_sort).toBe('[{"desc":false,"id":"week"},{"desc":true,"id":"fantasy_points"}]');
    expect(datasetQuery(state, stats)).toEqual({
      season: "2024",
      week: "10",
      team: "CIN",
      sort: "receiving_yards",
      order: "asc",
      limit: "100",
      offset: "50",
    });
    expect(Object.keys(datasetQuery(state, stats)).some((key) => key.startsWith("ui_"))).toBe(false);
    const request = listRequest(stats, state);
    expect(request.search).toEqual(datasetQuery(state, stats));
    expect(request.queryKey).toEqual(["list", stats.apiPath, request.search]);
    expect(normalizeTableSearch(written, stats)).toEqual(written);
  });

  it("drops malformed page state without erasing valid dataset state", () => {
    const state = readTableState(
      {
        season: "2024",
        week: "abc",
        team: "C",
        q: "nope",
        sort: "not-a-column",
        order: "sideways",
        limit: "900",
        offset: "2147483648",
        ui_sort: "{",
        ui_filters: JSON.stringify({
          missing: { kind: "text", value: "x" },
          team: { kind: "text", value: "XX" },
          fantasy_points: { kind: "range", min: 5, max: 1 },
          week: { kind: "range", min: 1, max: 2 },
          player_display_name: { kind: "text", value: "x".repeat(101) },
        }),
        ui_search: "y".repeat(101),
        ui_hidden: JSON.stringify(stats.columns),
        ui_widths: JSON.stringify({ player_display_name: 10, week: 200, nope: 100 }),
        ui_density: "roomy",
        extra: "ignored",
      },
      stats,
    );
    expect(state.filters).toEqual({ season: "2024" });
    expect(state.sort).toBe(stats.defaultSort);
    expect(state.order).toBe(stats.defaultOrder);
    expect(state.limit).toBe(50);
    expect(state.offset).toBe(0);
    expect(state.ui.sort).toEqual([]);
    expect(state.ui.filters).toEqual({ week: { kind: "range", min: 1, max: 2 } });
    expect(state.ui.search).toBe("");
    expect(state.ui.hidden).toEqual([]);
    expect(state.ui.widths).toEqual({ week: 200 });
    expect(state.ui.density).toBe("comfortable");
    expect(writeTableState(state, stats)).toEqual({
      season: "2024",
      ui_filters: '{"week":{"kind":"range","max":2,"min":1}}',
      ui_widths: '{"week":200}',
    });
  });

  it("keeps the first of duplicate sorts and only three priorities", () => {
    const state = readTableState(
      {
        ui_sort: JSON.stringify([
          { id: "week", desc: false },
          { id: "week", desc: true },
          { desc: "no" },
          { id: "season", desc: true },
          { id: "team", desc: false },
          { id: "position", desc: true },
        ]),
      },
      stats,
    );
    expect(state.ui.sort).toEqual([
      { id: "week", desc: false },
      { id: "season", desc: true },
      { id: "team", desc: false },
    ]);
  });

  it("ignores an invalid games week and leaves the other resources' defaults", () => {
    expect(writeTableState(readTableState({ week: "abc", season: "1998" }, games), games)).toEqual({});
    expect(writeTableState(readTableState({ week: "01", season: " 2020 " }, games), games)).toEqual({
      season: "2020",
      week: "1",
    });
    expect(writeTableState(readTableState({ position: "wr", q: "a", status: "x".repeat(65) }, players), players)).toEqual({
      position: "WR",
    });
    expect(writeTableState(readTableState({}, teams), teams)).toEqual({});
  });
});
