import { describe, expect, it } from "vitest";
import { buildCsv, csvFilename, csvField } from "./csv";
import type { Row } from "./api";

function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = "";
  let quoted = false;
  for (let index = 0; index < text.length; index += 1) {
    const char = text[index];
    if (quoted) {
      if (char === '"') {
        if (text[index + 1] === '"') {
          field += '"';
          index += 1;
        } else quoted = false;
      } else field += char;
    } else if (char === '"') quoted = true;
    else if (char === ",") {
      row.push(field);
      field = "";
    } else if (char === "\n") {
      row.push(field);
      rows.push(row);
      row = [];
      field = "";
    } else if (char !== "\r") field += char;
  }
  return rows;
}

describe("page CSV", () => {
  it("exports the logical rows and visible keys with CRLF and no decoration", () => {
    const source: Row[] = [
      { player_display_name: "Sample", fantasy_points: 1.5, team: "XX" },
      { player_display_name: "Other", fantasy_points: 2, team: "YY" },
    ];
    const before = JSON.stringify(source);
    const csv = buildCsv(["player_display_name", "fantasy_points"], source);
    expect(csv.startsWith("\uFEFF")).toBe(false);
    expect(csv.includes("\r\n")).toBe(true);
    expect(csv).not.toContain("nflverse");
    expect(csv).not.toContain("Sample,1.5,XX");
    const parsed = parseCsv(csv);
    expect(parsed).toEqual([
      ["player_display_name", "fantasy_points"],
      ["Sample", "1.5"],
      ["Other", "2"],
    ]);
    expect(JSON.stringify(source)).toBe(before);
    expect(csvFilename("stats", new Date("2026-11-10T17:00:00.000Z"))).toBe("seam-finder-stats-20261110-120000-ET.csv");
    expect(csvFilename("load-runs", new Date("2026-11-10T17:00:00.000Z"))).toContain("seam-finder-load-runs-");
  });

  it("escapes RFC 4180 text and prefixes formula-like cells, including negatives", () => {
    const source: Row[] = [
      {
        name: 'say "hi"',
        comma: "a,b",
        lines: "one\r\ntwo",
        formula: "=1+1",
        plus: "+1",
        at: "@cmd",
        tab: "\t=1",
        spaced: "  =cmd",
        points: -2.5,
        empty: null,
        flag: false,
      },
    ];
    const before = JSON.stringify(source);
    const columns = Object.keys(source[0]);
    const parsed = parseCsv(buildCsv(columns, source));
    expect(parsed[1]).toEqual(['say "hi"', "a,b", "one\r\ntwo", "'=1+1", "'+1", "'@cmd", "'\t=1", "'  =cmd", "'-2.5", "", "false"]);
    expect(csvField(-2.5)).toBe("'-2.5");
    expect(JSON.stringify(source)).toBe(before);
  });
});
