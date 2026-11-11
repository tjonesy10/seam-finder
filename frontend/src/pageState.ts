import type { Search } from "./api";
import { columnMeta, initialWidth, type ColumnMeta } from "./columns";
import type { Resource } from "./resources";

export type SortEntry = { id: string; desc: boolean };

export type TextFilter = { kind: "text"; value: string };
export type RangeFilter = { kind: "range"; min: number | null; max: number | null };
export type MultiFilter = { kind: "multi"; values: string[]; missing: boolean };
export type ColumnFilter = TextFilter | RangeFilter | MultiFilter;

export type PageUi = {
  sort: SortEntry[];
  filters: Record<string, ColumnFilter>;
  search: string;
  hidden: string[];
  widths: Record<string, number>;
  density: "comfortable" | "compact";
};

export type TableState = {
  filters: Record<string, string>;
  sort: string;
  order: "asc" | "desc";
  limit: number;
  offset: number;
  ui: PageUi;
};

export function emptyUi(): PageUi {
  return { sort: [], filters: {}, search: "", hidden: [], widths: {}, density: "comfortable" };
}

function blank(raw: string | undefined): string | null {
  if (raw === undefined) return null;
  const text = raw.trim();
  return text === "" ? null : text;
}

function parseBounded(raw: string | undefined, limit = 64): string | null {
  const text = blank(raw);
  if (text === null || text.length > limit) return null;
  return text;
}

function parseLetters(raw: string | undefined, low: number, high: number): string | null {
  const text = blank(raw);
  if (text === null || new RegExp(`^[A-Za-z]{${low},${high}}$`).test(text) === false) return null;
  return text.toUpperCase();
}

function parseIntText(raw: string | undefined, low: number, high: number): string | null {
  const text = blank(raw);
  if (text === null || /^\d{1,10}$/.test(text) === false) return null;
  const value = Number(text);
  if (value < low || value > high) return null;
  return String(value);
}

export function parseLimit(raw: string | undefined): number | null {
  const text = parseIntText(raw, 1, 500);
  return text === null ? null : Number(text);
}

function parseOffset(raw: string | undefined): number {
  const text = blank(raw);
  if (text === null) return 0;
  if (/^\d{1,10}$/.test(text) === false) return 0;
  const value = Number(text);
  if (value > 2147483647) return 0;
  return value;
}

function parseDatasetValue(kind: string, raw: string | undefined): string | null {
  if (kind === "season") return parseIntText(raw, 1999, 2100);
  if (kind === "week") return parseIntText(raw, 1, 22);
  if (kind === "season_type") {
    const text = blank(raw);
    if (text === null) return null;
    const value = text.toUpperCase();
    return value === "REG" || value === "POST" ? value : null;
  }
  if (kind === "team") return parseLetters(raw, 2, 3);
  if (kind === "position") return parseLetters(raw, 1, 5);
  if (kind === "q") {
    const text = blank(raw);
    if (text === null || text.length < 2 || text.length > 50) return null;
    return text;
  }
  return parseBounded(raw);
}

function coerceStrings(input: Record<string, unknown>): Search {
  const result: Search = {};
  for (const [key, value] of Object.entries(input)) {
    if (typeof value === "string") result[key] = value;
    else if (typeof value === "number" || typeof value === "boolean") result[key] = String(value);
  }
  return result;
}

function parseJson(value: string | undefined): { ok: true; value: unknown } | { ok: false } {
  if (!value) return { ok: false };
  try {
    return { ok: true, value: JSON.parse(value) };
  } catch {
    return { ok: false };
  }
}

function codeCompare(a: string, b: string): number {
  if (a < b) return -1;
  if (a > b) return 1;
  return 0;
}

function readSort(value: string | undefined, resource: Resource): SortEntry[] {
  const parsed = parseJson(value);
  if (!parsed.ok || !Array.isArray(parsed.value)) return [];
  const seen = new Set<string>();
  const result: SortEntry[] = [];
  for (const entry of parsed.value) {
    if (!entry || typeof entry !== "object" || Array.isArray(entry)) continue;
    const record = entry as { id?: unknown; desc?: unknown };
    if (typeof record.id !== "string" || typeof record.desc !== "boolean") continue;
    if (!resource.columns.includes(record.id) || seen.has(record.id)) continue;
    seen.add(record.id);
    result.push({ id: record.id, desc: record.desc });
    if (result.length === 3) break;
  }
  return result;
}

function readFilter(entry: unknown, meta: ColumnMeta): ColumnFilter | null {
  if (!entry || typeof entry !== "object" || Array.isArray(entry)) return null;
  const record = entry as { kind?: unknown; value?: unknown; min?: unknown; max?: unknown; values?: unknown; missing?: unknown };
  if (record.kind !== meta.filter) return null;
  if (record.kind === "text") {
    if (typeof record.value !== "string" || record.value.length > 100) return null;
    const trimmed = record.value.trim();
    if (trimmed === "") return null;
    return { kind: "text", value: trimmed };
  }
  if (record.kind === "range") {
    const minOk = record.min === null || (typeof record.min === "number" && Number.isFinite(record.min));
    const maxOk = record.max === null || (typeof record.max === "number" && Number.isFinite(record.max));
    if (!minOk || !maxOk) return null;
    const min = record.min as number | null;
    const max = record.max as number | null;
    if (min === null && max === null) return null;
    if (min !== null && max !== null && min > max) return null;
    return { kind: "range", min, max };
  }
  if (!Array.isArray(record.values) || typeof record.missing !== "boolean") return null;
  if (!record.values.every((item) => typeof item === "string")) return null;
  const values = [...new Set(record.values.map((item) => item.trim().toLocaleUpperCase("en-US")).filter((item) => item !== ""))].sort(codeCompare).slice(0, 64);
  if (values.length === 0 && !record.missing) return null;
  return { kind: "multi", values, missing: record.missing };
}

function readFilters(value: string | undefined, resource: Resource): Record<string, ColumnFilter> {
  const parsed = parseJson(value);
  if (!parsed.ok || !parsed.value || typeof parsed.value !== "object" || Array.isArray(parsed.value)) return {};
  const filters: Record<string, ColumnFilter> = {};
  for (const [key, entry] of Object.entries(parsed.value as Record<string, unknown>)) {
    if (!resource.columns.includes(key)) continue;
    const filter = readFilter(entry, columnMeta(key));
    if (filter) filters[key] = filter;
  }
  return filters;
}

function readSearch(value: string | undefined): string {
  if (!value || value.length > 100) return "";
  return value.trim();
}

function readHidden(value: string | undefined, resource: Resource): string[] {
  const parsed = parseJson(value);
  if (!parsed.ok || !Array.isArray(parsed.value)) return [];
  const hidden = [...new Set(parsed.value.filter((item): item is string => typeof item === "string" && resource.columns.includes(item)))].sort(codeCompare);
  if (hidden.length >= resource.columns.length) return [];
  return hidden;
}

function readWidths(value: string | undefined, resource: Resource): Record<string, number> {
  const parsed = parseJson(value);
  if (!parsed.ok || !parsed.value || typeof parsed.value !== "object" || Array.isArray(parsed.value)) return {};
  const widths: Record<string, number> = {};
  for (const [key, width] of Object.entries(parsed.value as Record<string, unknown>)) {
    if (!resource.columns.includes(key)) continue;
    if (typeof width !== "number" || !Number.isInteger(width) || width < 96 || width > 480) continue;
    if (width === initialWidth(key)) continue;
    widths[key] = width;
  }
  return widths;
}

function readUi(raw: Search, resource: Resource): PageUi {
  return {
    sort: readSort(raw.ui_sort, resource),
    filters: readFilters(raw.ui_filters, resource),
    search: readSearch(raw.ui_search),
    hidden: readHidden(raw.ui_hidden, resource),
    widths: readWidths(raw.ui_widths, resource),
    density: raw.ui_density === "compact" ? "compact" : "comfortable",
  };
}

export function readTableState(input: Record<string, unknown>, resource: Resource): TableState {
  const raw = coerceStrings(input);
  const filters: Record<string, string> = {};
  for (const field of resource.filters) {
    const value = parseDatasetValue(field.kind, raw[field.name]);
    if (value !== null) filters[field.name] = value;
  }
  const sortText = blank(raw.sort);
  const sort = sortText !== null && resource.sorts.includes(sortText) ? sortText : resource.defaultSort;
  const orderText = blank(raw.order)?.toLowerCase();
  const order = orderText === "asc" || orderText === "desc" ? orderText : resource.defaultOrder;
  const limit = parseLimit(raw.limit) ?? 50;
  return { filters, sort, order, limit, offset: parseOffset(raw.offset), ui: readUi(raw, resource) };
}

export function stableStringify(value: unknown): string {
  if (value === null || typeof value === "number" || typeof value === "boolean" || typeof value === "string") {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) return `[${value.map((item) => stableStringify(item)).join(",")}]`;
  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>).sort(([left], [right]) => codeCompare(left, right));
    return `{${entries.map(([key, item]) => `${JSON.stringify(key)}:${stableStringify(item)}`).join(",")}}`;
  }
  return "null";
}

export function writeTableState(state: TableState, resource: Resource): Search {
  const search: Search = {};
  for (const field of resource.filters) {
    const value = state.filters[field.name];
    if (value) search[field.name] = value;
  }
  if (state.sort !== resource.defaultSort) search.sort = state.sort;
  if (state.order !== resource.defaultOrder) search.order = state.order;
  if (state.limit !== 50) search.limit = String(state.limit);
  if (state.offset !== 0) search.offset = String(state.offset);
  if (state.ui.sort.length > 0) search.ui_sort = stableStringify(state.ui.sort);
  if (Object.keys(state.ui.filters).length > 0) search.ui_filters = stableStringify(state.ui.filters);
  if (state.ui.search) search.ui_search = state.ui.search;
  if (state.ui.hidden.length > 0) search.ui_hidden = stableStringify([...state.ui.hidden].sort(codeCompare));
  if (Object.keys(state.ui.widths).length > 0) search.ui_widths = stableStringify(state.ui.widths);
  if (state.ui.density === "compact") search.ui_density = "compact";
  return search;
}

export function normalizeTableSearch(input: Record<string, unknown>, resource: Resource): Search {
  return writeTableState(readTableState(input, resource), resource);
}

export function searchRecord(searchStr: string): Record<string, string> {
  const query = searchStr.startsWith("?") ? searchStr.slice(1) : searchStr;
  const params = new URLSearchParams(query);
  const result: Record<string, string> = {};
  for (const [key, value] of params.entries()) result[key] = value;
  return result;
}

export function datasetQuery(state: TableState, resource: Resource): Search {
  const search: Search = {};
  for (const field of resource.filters) {
    const value = state.filters[field.name];
    if (value) search[field.name] = value;
  }
  if (state.sort !== resource.defaultSort) search.sort = state.sort;
  if (state.order !== resource.defaultOrder) search.order = state.order;
  if (state.limit !== 50) search.limit = String(state.limit);
  if (state.offset !== 0) search.offset = String(state.offset);
  for (const key of Object.keys(search)) {
    if (key.startsWith("ui_")) delete search[key];
  }
  return search;
}

export function listRequest(resource: Resource, state: TableState): { search: Search; queryKey: readonly ["list", string, Search] } {
  const search = datasetQuery(state, resource);
  return { search, queryKey: ["list", resource.apiPath, search] };
}

export function withDatasetForm(current: TableState, resource: Resource, input: Search): TableState {
  const next = readTableState({ ...input, offset: "0" }, resource);
  return { ...next, ui: current.ui, offset: 0 };
}

export function withOffset(current: TableState, offset: number): TableState {
  return { ...current, offset: Math.max(0, offset) };
}
