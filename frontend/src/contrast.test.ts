import { describe, expect, it } from "vitest";
import { tokenSheet } from "./tokens";

function channel(value: number): number {
  const scaled = value / 255;
  return scaled <= 0.04045 ? scaled / 12.92 : ((scaled + 0.055) / 1.055) ** 2.4;
}

function luminance(hex: string): number {
  const value = Number.parseInt(hex.slice(1), 16);
  const red = channel((value >> 16) & 255);
  const green = channel((value >> 8) & 255);
  const blue = channel(value & 255);
  return 0.2126 * red + 0.7152 * green + 0.0722 * blue;
}

function ratio(foreground: string, background: string): number {
  const lighter = Math.max(luminance(foreground), luminance(background));
  const darker = Math.min(luminance(foreground), luminance(background));
  return (lighter + 0.05) / (darker + 0.05);
}

describe("design tokens", () => {
  it("meets the text and control contrast floors", () => {
    const token = (name: string) => {
      const match = tokenSheet.match(new RegExp(`${name}:\\s*(#[0-9a-fA-F]{6})`));
      expect(match, name).toBeTruthy();
      return match?.[1] ?? "";
    };
    const canvas = token("--color-canvas");
    const surface = token("--color-surface");
    const raised = token("--color-raised");
    const text = token("--color-text");
    const muted = token("--color-muted");
    const accent = token("--color-accent");
    const onAccent = token("--color-on-accent");
    const pairs: Array<[string, string, number]> = [
      [text, canvas, 4.5],
      [text, surface, 4.5],
      [text, raised, 4.5],
      [muted, canvas, 4.5],
      [muted, surface, 4.5],
      [muted, raised, 4.5],
      [accent, canvas, 4.5],
      [onAccent, accent, 4.5],
      [token("--color-danger"), surface, 4.5],
      [token("--color-success"), surface, 4.5],
      [token("--color-warning"), surface, 4.5],
      [token("--color-focus"), canvas, 3],
      [token("--color-control-border"), canvas, 3],
      [token("--color-control-border"), surface, 3],
      [token("--color-control-border"), raised, 3],
    ];
    for (const [foreground, background, minimum] of pairs) {
      expect(ratio(foreground, background)).toBeGreaterThanOrEqual(minimum);
    }
  });
});
