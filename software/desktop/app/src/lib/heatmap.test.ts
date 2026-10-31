import { describe, expect, it } from "vitest";
import { px, report, unknown } from "./fixtures";
import { metric, metricSet } from "./format";
import { bestUnit, cells, colour } from "./heatmap";

describe("heatmap", () => {
  it("lays out every region, shading only those with data", () => {
    const grid = cells(report, bestUnit(report));
    expect(bestUnit(report)).toBe("px");
    expect(grid).toHaveLength(9);
    expect(grid[0]).toMatchObject({ value: 20, shade: 0 });
    expect(grid[2]).toMatchObject({ value: 60, shade: 1 });
    expect(grid[4]!.shade).toBeCloseTo(0.5);
    expect(grid[8]).toMatchObject({ value: null, shade: null, samples: 0 });
    expect(colour(null)).toContain("0%");
  });

  it("never shows a number for an unknown unit", () => {
    expect(cells(report, "mm").every((c) => c.value === null)).toBe(true);
    expect(metricSet(px(41.6))).toBe("41.6 px");
    expect(metric(unknown, "mm")).toBe("unknown");
  });
});
