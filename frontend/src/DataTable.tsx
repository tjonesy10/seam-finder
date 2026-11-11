import { useEffect, useRef } from "react";
import type { ColumnFiltersState, OnChangeFn, RowData, SortingState } from "@tanstack/react-table";
import { flexRender } from "@tanstack/react-table";
import {
  getCoreRowModel,
  getFilteredRowModel,
  getSortedRowModel,
  useLegacyTable,
  type LegacyColumnDef,
} from "@tanstack/react-table/legacy";
import { useVirtualizer } from "@tanstack/react-virtual";
import styles from "./DataTable.module.css";

export type RowToggle = { locked?: boolean; excluded?: boolean };

export type DataTableHandle = {
  setRowToggle: (rowId: string, toggle: RowToggle) => void;
};

type DataTableProps<T extends RowData> = {
  data: T[];
  columns: LegacyColumnDef<T>[];
  getRowId: (row: T) => string;
  sorting: SortingState;
  onSortingChange: OnChangeFn<SortingState>;
  columnFilters: ColumnFiltersState;
  onColumnFiltersChange: OnChangeFn<ColumnFiltersState>;
  rowToggles?: Record<string, RowToggle>;
  onRowTogglesChange?: (toggles: Record<string, RowToggle>) => void;
  manual?: boolean;
  toggleHandle?: { current: DataTableHandle | null };
};

const ROW_HEIGHT = 36;

export function DataTable<T extends RowData>({
  data,
  columns,
  getRowId,
  sorting,
  onSortingChange,
  columnFilters,
  onColumnFiltersChange,
  rowToggles,
  onRowTogglesChange,
  manual = false,
  toggleHandle,
}: DataTableProps<T>) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const toggles = rowToggles ?? {};

  useEffect(() => {
    if (!toggleHandle) return;
    toggleHandle.current = {
      setRowToggle(rowId, toggle) {
        onRowTogglesChange?.({
          ...toggles,
          [rowId]: { ...toggles[rowId], ...toggle },
        });
      },
    };
    return () => {
      toggleHandle.current = null;
    };
  }, [toggleHandle, toggles, onRowTogglesChange]);

  const table = useLegacyTable({
    data,
    columns,
    state: { sorting, columnFilters },
    onSortingChange,
    onColumnFiltersChange,
    getRowId: (row) => getRowId(row),
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: manual ? undefined : getSortedRowModel(),
    getFilteredRowModel: manual ? undefined : getFilteredRowModel(),
    manualSorting: manual,
    manualFiltering: manual,
  });

  const rows = table.getRowModel().rows;
  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => ROW_HEIGHT,
    overscan: 8,
    initialRect: { width: 800, height: 512 },
  });
  const virtualRows = virtualizer.getVirtualItems();
  const paddingTop = virtualRows.length > 0 ? virtualRows[0].start : 0;
  const paddingBottom =
    virtualRows.length > 0 ? virtualizer.getTotalSize() - virtualRows[virtualRows.length - 1].end : 0;

  return (
    <div className={styles.scroll} ref={scrollRef} tabIndex={0} role="region" aria-label="Table rows">
      <table className={styles.table}>
        <thead>
          {table.getHeaderGroups().map((group) => (
            <tr key={group.id}>
              {group.headers.map((header) => (
                <th key={header.id}>
                  {header.isPlaceholder
                    ? null
                    : flexRender(header.column.columnDef.header, header.getContext())}
                </th>
              ))}
            </tr>
          ))}
        </thead>
        <tbody>
          {paddingTop > 0 ? (
            <tr>
              <td style={{ height: paddingTop, border: "none", padding: 0 }} />
            </tr>
          ) : null}
          {virtualRows.map((virtualRow) => {
            const row = rows[virtualRow.index];
            return (
              <tr key={row.id} data-row-id={row.id} style={{ height: ROW_HEIGHT }}>
                {row.getAllCells().map((cell) => (
                  <td key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>
                ))}
              </tr>
            );
          })}
          {paddingBottom > 0 ? (
            <tr>
              <td style={{ height: paddingBottom, border: "none", padding: 0 }} />
            </tr>
          ) : null}
        </tbody>
      </table>
    </div>
  );
}
