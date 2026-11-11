import { formatEtStamp } from "./format";
import { plainDecimal } from "./refine";
import type { Row } from "./api";

function serializeRaw(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") return plainDecimal(value);
  return String(value);
}

export function guardFormula(text: string): string {
  if (text === "") return text;
  const first = text[0];
  if ("=+-@\t\r\n".includes(first)) return `'${text}`;
  const lead = text.trimStart()[0];
  if (lead === "=" || lead === "+" || lead === "-" || lead === "@") return `'${text}`;
  return text;
}

export function escapeRfc4180(text: string): string {
  if (/[",\r\n]/.test(text)) return `"${text.replaceAll('"', '""')}"`;
  return text;
}

export function csvField(value: unknown): string {
  return escapeRfc4180(guardFormula(serializeRaw(value)));
}

export function buildCsv(columns: string[], rows: Row[]): string {
  const lines = [columns.map((key) => csvField(key)).join(",")];
  for (const row of rows) lines.push(columns.map((key) => csvField(row[key])).join(","));
  return `${lines.join("\r\n")}\r\n`;
}

export function csvFilename(slug: string, now: Date): string {
  return `seam-finder-${slug}-${formatEtStamp(now)}-ET.csv`;
}

export function downloadCsv(filename: string, body: string): void {
  const blob = new Blob([body], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
