import { columnMap, type ColumnMeta, type ValueKind } from "./columns";
import type { Row } from "./api";
import type { ColumnFilter, PageUi, SortEntry } from "./pageState";
import type { Resource } from "./resources";

const collator = new Intl.Collator("en-US", { sensitivity: "accent", numeric: false, usage: "sort" });

export function plainDecimal(value: number): string {
  if (!Number.isFinite(value) || Object.is(value, -0)) return Object.is(value, -0) ? "0" : "";
  const text = value.toString();
  if (!text.includes("e") && !text.includes("E")) return text;
  const negative = value < 0;
  const expanded = Math.abs(value).toLocaleString("en-US", { useGrouping: false, maximumFractionDigits: 20 });
  return negative ? `-${expanded}` : expanded;
}

export function rawScalar(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") return plainDecimal(value);
  return String(value);
}

export function cycleHeaderSort(current: SortEntry[], column: string, shift: boolean): SortEntry[] {
  const index = current.findIndex((entry) => entry.id === column);
  const existing = index >= 0 ? current[index] : null;
  if (!shift) {
    if (!existing) return [{ id: column, desc: false }];
    if (!existing.desc) return [{ id: column, desc: true }];
    return [];
  }
  if (!existing) {
    if (current.length >= 3) return current;
    return [...current, { id: column, desc: false }];
  }
  if (!existing.desc) {
    const next = current.slice();
    next[index] = { id: column, desc: true };
    return next;
  }
  return current.filter((entry) => entry.id !== column);
}

export function moveSort(current: SortEntry[], index: number, direction: -1 | 1): SortEntry[] {
  const target = index + direction;
  if (index < 0 || index >= current.length || target < 0 || target >= current.length) return current;
  const next = current.slice();
  const [entry] = next.splice(index, 1);
  next.splice(target, 0, entry);
  return next;
}

export function toggleSortDirection(current: SortEntry[], index: number): SortEntry[] {
  if (!current[index]) return current;
  const next = current.slice();
  next[index] = { ...current[index], desc: !current[index].desc };
  return next;
}

export function removeSort(current: SortEntry[], index: number): SortEntry[] {
  return current.filter((_, item) => item !== index);
}

export function addSort(current: SortEntry[], id: string, desc: boolean): SortEntry[] {
  if (current.length >= 3 || current.some((entry) => entry.id === id)) return current;
  return [...current, { id, desc }];
}

function prepare(value: unknown, kind: ValueKind): number | boolean | string | null {
  if (value === null || value === undefined) return null;
  if (kind === "integer" || kind === "year" || kind === "points" || kind === "line" || kind === "percent") {
    return typeof value === "number" && Number.isFinite(value) ? value : null;
  }
  if (kind === "boolean") return typeof value === "boolean" ? value : null;
  if (kind === "date" || kind === "timestamp") {
    if (typeof value !== "string") return null;
    const time = Date.parse(value);
    return Number.isNaN(time) ? null : time;
  }
  return String(value);
}

function comparePrepared(left: number | boolean | string, right: number | boolean | string, kind: ValueKind): number {
  if (typeof left === "number" && typeof right === "number") return left - right;
  if (typeof left === "boolean" && typeof right === "boolean") return Number(left) - Number(right);
  if (kind === "text" || kind === "identifier" || kind === "date" || kind === "timestamp") {
    return collator.compare(String(left), String(right));
  }
  return collator.compare(String(left), String(right));
}

export function compareRows(left: Row, right: Row, sorts: SortEntry[], metas: Map<string, ColumnMeta>, rowId: (row: Row) => string): number {
  for (const sort of sorts) {
    const kind = metas.get(sort.id)?.kind ?? "text";
    const a = prepare(left[sort.id], kind);
    const b = prepare(right[sort.id], kind);
    if (a === null && b === null) continue;
    if (a === null) return 1;
    if (b === null) return -1;
    const base = comparePrepared(a, b, kind);
    if (base !== 0) return sort.desc ? -base : base;
  }
  const leftId = rowId(left);
  const rightId = rowId(right);
  if (leftId < rightId) return -1;
  if (leftId > rightId) return 1;
  return 0;
}

function includesLiteral(haystack: string, needle: string): boolean {
  return haystack.toLocaleLowerCase("en-US").includes(needle.toLocaleLowerCase("en-US"));
}

function matchesFilter(value: unknown, filter: ColumnFilter): boolean {
  if (filter.kind === "text") return includesLiteral(rawScalar(value), filter.value.trim());
  if (filter.kind === "range") {
    if (filter.min === null && filter.max === null) return true;
    if (typeof value !== "number" || !Number.isFinite(value)) return false;
    if (filter.min !== null && value < filter.min) return false;
    if (filter.max !== null && value > filter.max) return false;
    return true;
  }
  if (value === null || value === undefined) return filter.missing;
  const token = String(value).trim().toLocaleUpperCase("en-US");
  return filter.values.includes(token);
}

export function rowMatches(row: Row, ui: Pick<PageUi, "filters" | "search">, columns: string[]): boolean {
  const needle = ui.search.trim();
  if (needle !== "") {
    const found = columns.some((key) => includesLiteral(rawScalar(row[key]), needle));
    if (!found) return false;
  }
  return Object.entries(ui.filters).every(([key, filter]) => matchesFilter(row[key], filter));
}

export function logicalRows(rows: Row[], ui: PageUi, resource: Resource): Row[] {
  const columns = resource.columns;
  const filtered = rows.filter((row) => rowMatches(row, ui, columns));
  if (ui.sort.length === 0) return filtered;
  const metas = columnMap(resource);
  return filtered
    .map((row, index) => ({ row, index }))
    .sort((left, right) => {
      const compared = compareRows(left.row, right.row, ui.sort, metas, resource.rowId);
      return compared === 0 ? left.index - right.index : compared;
    })
    .map((item) => item.row);
}

/** Manual rows for the loaded API page. DataTable does not call this. */
export function pageManualRows(rows: Row[], ui: PageUi, resource: Resource): Row[] {
  return logicalRows(rows, ui, resource);
}

export function pageExport(
  loadedRows: Row[],
  ui: PageUi,
  resource: Resource,
  visibleKeys: string[],
): { columns: string[]; rows: Row[] } {
  return { columns: visibleKeys, rows: pageManualRows(loadedRows, ui, resource) };
}

export function parseDecimalInput(raw: string): number | null | "invalid" {
  const text = raw.trim();
  if (text === "") return null;
  if (/^[+-]?(?:\d+\.?\d*|\.\d+)$/.test(text) === false) return "invalid";
  const value = Number(text);
  return Number.isFinite(value) ? value : "invalid";
}

export function multiOptions(rows: Row[], key: string, selected: string[]): string[] {
  const values = new Set<string>(selected);
  for (const row of rows) {
    if (row[key] === null || row[key] === undefined) continue;
    const token = String(row[key]).trim().toLocaleUpperCase("en-US");
    if (token !== "") values.add(token);
  }
  return [...values].sort((left, right) => (left < right ? -1 : left > right ? 1 : 0));
}
