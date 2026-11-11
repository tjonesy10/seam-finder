import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";
import { PremiumTable } from "./PremiumTable";
import { readTableState, type TableState } from "./pageState";
import { games, loadRuns, players, stats, teams } from "./resources";
import type { Row } from "./api";

const rows: Row[] = Array.from({ length: 5000 }, (_, index) => ({
  gsis_id: `P${String(index).padStart(4, "0")}`,
  player_display_name: `Sample Athlete ${index}`,
  season: 2026,
  week: (index % 18) + 1,
  season_type: "REG",
  game_id: `2026_${String((index % 18) + 1).padStart(2, "0")}_XX_YY`,
  team: index % 2 === 0 ? "XX" : "YY",
  opponent_team: "ZZ",
  position: index % 3 === 0 ? "QB" : "WR",
  position_group: "SKILL",
  fantasy_points: index % 17 === 0 ? null : index - 2500,
  fantasy_points_ppr: index - 2000,
  receiving_yards: index,
  target_share: index / 5000,
}));

function Harness({ width }: { width: number }) {
  const [state, setState] = useState<TableState>(() => readTableState({}, stats));
  return (
    <div style={{ width }}>
      <PremiumTable
        resource={stats}
        rows={rows}
        successfulRows={rows}
        state={state}
        phase="ready"
        fresh
        onState={(next) => setState(next)}
      />
    </div>
  );
}

function mounted(): HTMLElement[] {
  return [...document.querySelectorAll<HTMLElement>("[data-row-id]")];
}

function expectBounded(density: "comfortable" | "compact") {
  const nodes = mounted();
  expect(nodes.length).toBeGreaterThan(0);
  expect(nodes.length).toBeLessThanOrEqual(80);
  const height = density === "compact" ? 32 : 44;
  let previousEnd = Number(nodes[0].getAttribute("data-start"));
  for (const node of nodes) {
    const start = Number(node.getAttribute("data-start"));
    const end = Number(node.getAttribute("data-end"));
    expect(start).toBe(previousEnd);
    expect(end - start).toBe(height);
    expect(node.getAttribute("data-row-id")).toBeTruthy();
    previousEnd = end;
  }
  const region = document.querySelector("[aria-label='Table rows']");
  const total = Number(region?.getAttribute("data-virtual-total"));
  const top = document.querySelector("[data-spacer='top'] td");
  const bottom = document.querySelector("[data-spacer='bottom'] td");
  const paddingTop = top instanceof HTMLElement ? Number.parseFloat(top.style.height) : 0;
  const paddingBottom = bottom instanceof HTMLElement ? Number.parseFloat(bottom.style.height) : 0;
  expect(paddingTop + nodes.length * height + paddingBottom).toBe(total);
}

describe("stats virtual fixture", () => {
  it("keeps at most 80 data rows mounted through scroll, sort, filter, resize, and both densities", () => {
    expect(stats.columns.length).toBeGreaterThan(players.columns.length);
    expect(stats.columns.length).toBeGreaterThan(games.columns.length);
    expect(stats.columns.length).toBeGreaterThan(teams.columns.length);
    expect(stats.columns.length).toBeGreaterThan(loadRuns.columns.length);
    const { rerender } = render(<Harness width={1440} />);
    expectBounded("comfortable");
    const region = document.querySelector("[aria-label='Table rows']") as HTMLElement;
    let top = 0;
    Object.defineProperty(region, "scrollTop", {
      configurable: true,
      get: () => top,
      set: (value: number) => {
        top = value;
      },
    });
    top = 4999 * 44;
    fireEvent.scroll(region);
    const ids = mounted().map((node) => node.getAttribute("data-row-id"));
    expect(ids).toContain("P4999-2026-14");
    expectBounded("comfortable");

    fireEvent.click(screen.getByRole("button", { name: "Sort by Receiving yards" }));
    expectBounded("comfortable");
    fireEvent.click(screen.getByRole("button", { name: "Column filter for Team" }));
    fireEvent.click(screen.getByLabelText("XX"));
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    expect(mounted().length).toBeLessThanOrEqual(80);
    fireEvent.click(screen.getByRole("radio", { name: "Compact" }));
    expect(document.querySelector("[data-density='compact']")).not.toBeNull();
    expectBounded("compact");
    const handle = screen.getByRole("separator", { name: "Resize Player display name" });
    fireEvent.keyDown(handle, { key: "ArrowRight" });
    expect(screen.getByRole("separator", { name: "Resize Player display name" }).getAttribute("aria-valuenow")).toBe("256");
    fireEvent.keyDown(screen.getByRole("separator", { name: "Resize Player display name" }), { key: "Home" });
    expect(screen.getByRole("separator", { name: "Resize Player display name" }).getAttribute("aria-valuenow")).toBe("240");
    rerender(<Harness width={390} />);
    expect(mounted().length).toBeLessThanOrEqual(80);
  });
});
