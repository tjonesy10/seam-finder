import { act, useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ColumnFiltersState, SortingState } from "@tanstack/react-table";
import type { LegacyColumnDef } from "@tanstack/react-table/legacy";
import { DataTable, type DataTableHandle, type RowToggle } from "./DataTable";

type PoolRow = { id: string; name: string; points: number };

const columns: LegacyColumnDef<PoolRow>[] = [
  { accessorKey: "name", header: "name", filterFn: "includesString" },
  {
    accessorKey: "points",
    header: ({ column }) => (
      <button type="button" onClick={() => column.toggleSorting(true)}>
        points
      </button>
    ),
  },
];

const rows: PoolRow[] = Array.from({ length: 500 }, (_, index) => ({
  id: String(index),
  name: `Row ${index}`,
  points: index,
}));

function Harness({ toggleHandle }: { toggleHandle: { current: DataTableHandle | null } }) {
  const [sorting, setSorting] = useState<SortingState>([]);
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([]);
  const [rowToggles, setRowToggles] = useState<Record<string, RowToggle>>({});
  return (
    <>
      <button type="button" onClick={() => setColumnFilters([{ id: "name", value: "Row 499" }])}>
        Filter one
      </button>
      <DataTable
        data={rows}
        columns={columns}
        getRowId={(row) => row.id}
        sorting={sorting}
        onSortingChange={setSorting}
        columnFilters={columnFilters}
        onColumnFiltersChange={setColumnFilters}
        rowToggles={rowToggles}
        onRowTogglesChange={setRowToggles}
        toggleHandle={toggleHandle}
      />
      <pre data-testid="toggles">{JSON.stringify(rowToggles)}</pre>
    </>
  );
}

describe("DataTable", () => {
  it("virtualizes 500 rows and keeps sort, filter, and the toggle hook on stable ids", async () => {
    const toggleHandle: { current: DataTableHandle | null } = { current: null };
    render(<Harness toggleHandle={toggleHandle} />);
    const mounted = document.querySelectorAll("[data-row-id]");
    expect(mounted.length).toBeGreaterThan(0);
    expect(mounted.length).toBeLessThan(500);

    fireEvent.click(screen.getByRole("button", { name: "points" }));
    const sorted = [...document.querySelectorAll("[data-row-id]")].map((node) => node.getAttribute("data-row-id"));
    expect(sorted[0]).toBe("499");

    fireEvent.click(screen.getByRole("button", { name: "Filter one" }));
    const filtered = [...document.querySelectorAll("[data-row-id]")].map((node) => node.getAttribute("data-row-id"));
    expect(filtered).toContain("499");
    expect(filtered.every((id) => id === "499")).toBe(true);

    expect(toggleHandle.current).not.toBeNull();
    await act(async () => {
      toggleHandle.current?.setRowToggle("499", { locked: true });
    });
    expect(screen.getByTestId("toggles").textContent).toBe(JSON.stringify({ "499": { locked: true } }));
    expect(document.querySelector("[data-row-id='499']")).not.toBeNull();
    expect(columns).toHaveLength(2);
    expect(columns[0]).toMatchObject({ accessorKey: "name" });
    expect(columns[1]).toMatchObject({ accessorKey: "points" });
  });
});
