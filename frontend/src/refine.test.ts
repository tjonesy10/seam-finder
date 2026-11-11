import { describe, expect, it } from "vitest";
import { emptyUi, type PageUi } from "./pageState";
import { addSort, cycleHeaderSort, logicalRows, moveSort, pageExport, pageManualRows, plainDecimal, rawScalar, removeSort, toggleSortDirection } from "./refine";
import { stats } from "./resources";

const rows = [
  { gsis_id: "B", player_display_name: "Beta", season: 2026, week: 1, team: "yy", position: "WR", fantasy_points: 1, fantasy_points_ppr: null, receiving_yards: 10 },
  { gsis_id: "A", player_display_name: "alpha", season: 2026, week: 1, team: "XX", position: "QB", fantasy_points: 1, fantasy_points_ppr: -2.5, receiving_yards: null },
  { gsis_id: "C", player_display_name: null, season: 2026, week: 2, team: null, position: "WR", fantasy_points: null, fantasy_points_ppr: 4, receiving_yards: 2 },
  { gsis_id: "D", player_display_name: "Alpha", season: 2026, week: 2, team: "XX", position: "WR", fantasy_points: -4, fantasy_points_ppr: 4, receiving_yards: 2 },
];

function ui(patch: Partial<PageUi>): PageUi {
  return { ...emptyUi(), ...patch };
}

describe("page refinement", () => {
  it("cycles header sorts, caps priorities, and orders nulls last with a stable identity tie", () => {
    let sort = cycleHeaderSort([], "fantasy_points", false);
    expect(logicalRows(rows, ui({ sort }), stats).map((row) => row.gsis_id)).toEqual(["D", "A", "B", "C"]);
    sort = cycleHeaderSort(sort, "fantasy_points", false);
    expect(logicalRows(rows, ui({ sort }), stats).map((row) => row.gsis_id)).toEqual(["A", "B", "D", "C"]);
    sort = cycleHeaderSort(sort, "fantasy_points", false);
    expect(sort).toEqual([]);
    expect(logicalRows(rows, ui({ sort }), stats).map((row) => row.gsis_id)).toEqual(["B", "A", "C", "D"]);

    sort = cycleHeaderSort([], "player_display_name", false);
    sort = cycleHeaderSort(sort, "team", true);
    sort = cycleHeaderSort(sort, "position", true);
    expect(sort).toHaveLength(3);
    expect(cycleHeaderSort(sort, "week", true)).toEqual(sort);
    expect(addSort(sort, "week", false)).toEqual(sort);
    const moved = moveSort(sort, 2, -1);
    expect(moved.map((entry) => entry.id)).toEqual(["player_display_name", "position", "team"]);
    expect(toggleSortDirection(moved, 0)[0]).toEqual({ id: "player_display_name", desc: true });
    expect(removeSort(moved, 1)).toHaveLength(2);
    const tied = logicalRows(rows, ui({ sort: [{ id: "fantasy_points", desc: false }] }), stats);
    expect(tied[0].gsis_id).toBe("D");
    expect(tied[1].gsis_id).toBe("A");
    expect(tied[2].gsis_id).toBe("B");
  });

  it("applies inclusive ranges, exact team or position selections, and literal text together", () => {
    const filtered = logicalRows(
      rows,
      ui({
        filters: {
          fantasy_points: { kind: "range", min: -4, max: 1 },
          team: { kind: "multi", values: ["XX"], missing: false },
          position: { kind: "multi", values: ["WR"], missing: true },
          player_display_name: { kind: "text", value: "alpha" },
        },
      }),
      stats,
    );
    expect(filtered.map((row) => row.gsis_id)).toEqual(["D"]);
    const oneSided = logicalRows(rows, ui({ filters: { receiving_yards: { kind: "range", min: 10, max: null } } }), stats);
    expect(oneSided.map((row) => row.gsis_id)).toEqual(["B"]);
    const missingTeam = logicalRows(rows, ui({ filters: { team: { kind: "multi", values: [], missing: true } } }), stats);
    expect(missingTeam.map((row) => row.gsis_id)).toEqual(["C"]);
  });

  it("searches hidden columns and treats null as empty text", () => {
    const hidden = logicalRows(rows, ui({ search: "alpha", hidden: ["player_display_name"] }), stats);
    expect(hidden.map((row) => row.gsis_id)).toEqual(["A", "D"]);
    expect(logicalRows(rows, ui({ search: "null" }), stats)).toEqual([]);
    expect(rawScalar(null)).toBe("");
    expect(plainDecimal(-1.5)).toBe("-1.5");
    expect(logicalRows(rows, ui({ search: "-2.5" }), stats).map((row) => row.gsis_id)).toEqual(["A"]);
  });

  it("exports the last loaded page through the manual adapter", () => {
    const loaded = rows.slice(0, 2);
    const snapshot = pageExport(loaded, ui({ sort: [{ id: "gsis_id", desc: false }] }), stats, ["gsis_id", "team"]);
    expect(snapshot.columns).toEqual(["gsis_id", "team"]);
    expect(snapshot.rows.map((row) => row.gsis_id)).toEqual(["A", "B"]);
    expect(pageManualRows(rows, ui({}), stats)).toHaveLength(rows.length);
    expect(snapshot.rows).not.toBe(rows);
  });
});
