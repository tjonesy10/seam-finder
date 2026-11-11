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

export type ColumnCellMeta = {
  width?: number;
  numeric?: boolean;
  points?: boolean;
  pointsBgFor?: (value: unknown) => string | undefined;
  ariaSort?: "ascending" | "descending" | "none";
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
  density?: "comfortable" | "compact";
};

function readMeta(value: unknown): ColumnCellMeta {
  if (!value || typeof value !== "object") return {};
  return value as ColumnCellMeta;
}

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
  density = "comfortable",
}: DataTableProps<T>) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const toggles = rowToggles ?? {};
  const rowHeight = density === "compact" ? 32 : 44;
  const anchorRef = useRef<{ height: number; id: string | null }>({ height: rowHeight, id: null });
  const pendingAnchor = useRef<string | null>(null);

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
    estimateSize: () => rowHeight,
    overscan: 8,
    initialRect: { width: 800, height: 512 },
    getItemKey: (index) => rows[index]?.id ?? String(index),
  });
  const virtualRows = virtualizer.getVirtualItems();
  const paddingTop = virtualRows.length > 0 ? virtualRows[0].start : 0;
  const paddingBottom =
    virtualRows.length > 0 ? virtualizer.getTotalSize() - virtualRows[virtualRows.length - 1].end : 0;
  const topId = virtualRows.length > 0 ? rows[virtualRows[0].index]?.id ?? null : null;
  if (anchorRef.current.height !== rowHeight) pendingAnchor.current = anchorRef.current.id;
  anchorRef.current = { height: rowHeight, id: topId };

  useEffect(() => {
    const id = pendingAnchor.current;
    if (!id) return;
    pendingAnchor.current = null;
    const index = rows.findIndex((row) => row.id === id);
    if (index >= 0) virtualizer.scrollToIndex(index, { align: "start" });
  }, [rowHeight, rows, virtualizer]);

  const tableWidth = table.getVisibleLeafColumns().reduce((sum, column) => sum + (readMeta(column.columnDef.meta).width ?? 160), 0);

  return (
    <div
      className={styles.scroll}
      ref={scrollRef}
      tabIndex={0}
      role="region"
      aria-label="Table rows"
      data-density={density}
      data-virtual-total={virtualizer.getTotalSize()}
    >
      <table className={styles.table} style={{ width: tableWidth, minWidth: tableWidth, ["--row-height" as string]: `${rowHeight}px` }}>
        <thead>
          {table.getHeaderGroups().map((group) => (
            <tr key={group.id}>
              {group.headers.map((header) => {
                const meta = readMeta(header.column.columnDef.meta);
                const style = meta.width ? { width: meta.width, minWidth: meta.width, maxWidth: meta.width } : undefined;
                return (
                  <th key={header.id} aria-sort={meta.ariaSort} style={style} className={meta.numeric ? styles.numeric : undefined}>
                    {header.isPlaceholder ? null : flexRender(header.column.columnDef.header, header.getContext())}
                  </th>
                );
              })}
            </tr>
          ))}
        </thead>
        <tbody>
          {paddingTop > 0 ? (
            <tr data-spacer="top">
              <td style={{ height: paddingTop, border: "none", padding: 0 }} />
            </tr>
          ) : null}
          {virtualRows.map((virtualRow) => {
            const row = rows[virtualRow.index];
            return (
              <tr key={row.id} data-row-id={row.id} data-start={virtualRow.start} data-end={virtualRow.end} style={{ height: rowHeight }}>
                {row.getVisibleCells().map((cell) => {
                  const meta = readMeta(cell.column.columnDef.meta);
                  const pointsBg = meta.pointsBgFor?.(cell.getValue());
                  const style = {
                    ...(meta.width ? { width: meta.width, minWidth: meta.width, maxWidth: meta.width } : {}),
                    ...(pointsBg ? { backgroundColor: pointsBg } : {}),
                  };
                  const className = [meta.numeric ? styles.numeric : "", meta.points ? styles.points : ""].filter(Boolean).join(" ");
                  return (
                    <td key={cell.id} data-column={cell.column.id} className={className || undefined} style={style}>
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  );
                })}
              </tr>
            );
          })}
          {paddingBottom > 0 ? (
            <tr data-spacer="bottom">
              <td style={{ height: paddingBottom, border: "none", padding: 0 }} />
            </tr>
          ) : null}
        </tbody>
      </table>
    </div>
  );
}
