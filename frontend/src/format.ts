import type { ValueKind } from "./columns";
import { plainDecimal } from "./refine";

const integerFormat = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const yearFormat = new Intl.NumberFormat("en-US", { useGrouping: false, maximumFractionDigits: 0 });
const decimalFormat = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const percentFormat = new Intl.NumberFormat("en-US", {
  style: "percent",
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
});

const TEAL = ["#111c2e", "#102a30", "#0f3a36", "#0e4a42", "#0c564c"];
const NAVY = ["#111c2e", "#162438", "#1a2e48", "#1c3654", "#1e3e62"];

export const POINTS_LEGEND = "Points intensity, relative to this page";

export function formatTimestamp(value: string): string {
  const time = Date.parse(value);
  if (Number.isNaN(time)) return value;
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  }).formatToParts(new Date(time));
  const read = (type: string) => parts.find((part) => part.type === type)?.value ?? "";
  let hour = read("hour");
  if (hour === "24") hour = "00";
  return `${read("year")}-${read("month")}-${read("day")} ${hour}:${read("minute")}:${read("second")} ET`;
}

export function formatEtStamp(now: Date): string {
  return formatTimestamp(now.toISOString()).replace(" ET", "").replaceAll("-", "").replace(" ", "-").replaceAll(":", "");
}

export type DisplayValue = { text: string; missing: boolean };

export function formatValue(value: unknown, kind: ValueKind): DisplayValue {
  if (value === null || value === undefined) return { text: "—", missing: true };
  if (kind === "boolean") return { text: value === true ? "true" : value === false ? "false" : String(value), missing: false };
  if (kind === "date" || kind === "identifier" || kind === "text") return { text: String(value), missing: false };
  if (kind === "timestamp") return { text: formatTimestamp(String(value)), missing: false };
  if (typeof value !== "number" || !Number.isFinite(value)) return { text: String(value), missing: false };
  if (kind === "integer") return { text: integerFormat.format(value), missing: false };
  if (kind === "year") return { text: yearFormat.format(value), missing: false };
  if (kind === "percent") return { text: percentFormat.format(value), missing: false };
  if (kind === "points" || kind === "line") return { text: decimalFormat.format(value), missing: false };
  return { text: plainDecimal(value), missing: false };
}

function mixStep(palette: string[], amount: number): string {
  const index = Math.min(palette.length - 1, Math.max(0, Math.round(amount * (palette.length - 1))));
  return palette[index];
}

export function pointsExtent(values: unknown[]): { min: number | null; max: number | null } {
  const numbers = values.filter((value): value is number => typeof value === "number" && Number.isFinite(value));
  if (numbers.length === 0) return { min: null, max: null };
  return { min: Math.min(...numbers), max: Math.max(...numbers) };
}

export function pointsBackground(value: unknown, min: number | null, max: number | null): string | undefined {
  if (typeof value !== "number" || !Number.isFinite(value) || min === null || max === null || min === max) return undefined;
  if (min < 0 && max > 0) {
    if (value === 0) return undefined;
    if (value < 0) return mixStep(NAVY, value / min);
    return mixStep(TEAL, value / max);
  }
  const span = max - min;
  return mixStep(TEAL, (value - min) / span);
}

export const SCALE_BACKGROUNDS = [...new Set([...TEAL, ...NAVY])];

export function relativeLuminance(hex: string): number {
  const parsed = Number.parseInt(hex.slice(1), 16);
  const channel = (piece: number) => {
    const scaled = piece / 255;
    return scaled <= 0.04045 ? scaled / 12.92 : ((scaled + 0.055) / 1.055) ** 2.4;
  };
  const red = channel((parsed >> 16) & 255);
  const green = channel((parsed >> 8) & 255);
  const blue = channel(parsed & 255);
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
}

export function contrastRatio(foreground: string, background: string): number {
  const lighter = Math.max(relativeLuminance(foreground), relativeLuminance(background));
  const darker = Math.min(relativeLuminance(foreground), relativeLuminance(background));
  return (lighter + 0.05) / (darker + 0.05);
}
