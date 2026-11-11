import { describe, expect, it } from "vitest";
import { POINTS_LEGEND, SCALE_BACKGROUNDS, contrastRatio, formatEtStamp, formatTimestamp, formatValue, pointsBackground, pointsExtent } from "./format";

describe("display formatting", () => {
  it("formats public values without changing the raw input", () => {
    const points = 12.5;
    expect(formatValue(points, "points").text).toBe("12.50");
    expect(formatValue(-3.5, "line").text).toBe("-3.50");
    expect(formatValue(1234, "integer").text).toBe("1,234");
    expect(formatValue(2026, "year").text).toBe("2026");
    expect(formatValue(1, "year").text).toBe("1");
    expect(formatValue(0.256, "percent").text).toBe("25.6%");
    expect(formatValue(null, "points")).toEqual({ text: "—", missing: true });
    expect(formatValue(true, "boolean").text).toBe("true");
    expect(formatValue(false, "boolean").text).toBe("false");
    expect(formatValue("99-0000001", "identifier").text).toBe("99-0000001");
    expect(formatValue(1000, "identifier").text).toBe("1000");
    expect(formatValue("2026-09-01", "date").text).toBe("2026-09-01");
    expect(formatTimestamp("2026-11-05T17:00:00+00:00")).toBe("2026-11-05 12:00:00 ET");
    expect(formatEtStamp(new Date("2026-11-10T17:00:00.000Z"))).toBe("20261110-120000");
    expect(points).toBe(12.5);
    expect(POINTS_LEGEND).toBe("Points intensity, relative to this page");
  });

  it("keeps points scales neutral at the edges and above the contrast floor", () => {
    expect(pointsBackground(null, 0, 10)).toBeUndefined();
    expect(pointsBackground(1, null, null)).toBeUndefined();
    expect(pointsBackground(2, 2, 2)).toBeUndefined();
    const mixed = pointsExtent([-2, 0, 4, null]);
    expect(pointsBackground(0, mixed.min, mixed.max)).toBeUndefined();
    expect(pointsBackground(-2, mixed.min, mixed.max)).toBeTruthy();
    expect(pointsBackground(4, mixed.min, mixed.max)).toBeTruthy();
    const rising = pointsExtent([1, 3]);
    expect(pointsBackground(1, rising.min, rising.max)).toBe("#111c2e");
    expect(pointsBackground(3, rising.min, rising.max)).not.toBe(pointsBackground(1, rising.min, rising.max));
    for (const background of SCALE_BACKGROUNDS) {
      expect(contrastRatio("#e8eef7", background)).toBeGreaterThanOrEqual(4.5);
    }
  });
});
