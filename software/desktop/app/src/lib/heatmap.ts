// The accuracy heatmap: one cell per screen region, shaded by its median error.
import type { ValidationReport } from "./contracts/ValidationReport";

export type Unit = "px" | "mm" | "deg";

export interface Cell {
  col: number;
  row: number;
  samples: number;
  /** Median error in `unit`, or null where the region has no validation data or the unit is unknown. */
  value: number | null;
  /** 0 (best in this report) .. 1 (worst); null without a value. */
  shade: number | null;
}

/** The best unit the report has values in: degrees, else millimetres, else pixels. */
export function bestUnit(report: ValidationReport): Unit {
  const m = report.accuracy?.median;
  if (m?.deg.status === "available") return "deg";
  if (m?.mm.status === "available") return "mm";
  return "px";
}

export function cells(report: ValidationReport, unit: Unit): Cell[] {
  const out: Cell[] = [];
  for (let row = 0; row < report.region_rows; row++) {
    for (let col = 0; col < report.region_cols; col++) {
      const region = report.regions.find((r) => r.col === col && r.row === row);
      const m = region?.median[unit];
      out.push({ col, row, samples: region?.samples ?? 0, value: m?.status === "available" ? m.value : null, shade: null });
    }
  }
  const values = out.map((c) => c.value).filter((v): v is number => v !== null);
  if (values.length) {
    const lo = Math.min(...values);
    const hi = Math.max(...values);
    for (const c of out) if (c.value !== null) c.shade = hi > lo ? (c.value - lo) / (hi - lo) : 0;
  }
  return out;
}

/** Green (good) to red (poor); grey for no data. */
export function colour(shade: number | null): string {
  if (shade === null) return "hsl(0 0% 30%)";
  return `hsl(${Math.round(120 * (1 - shade))} 60% 40%)`;
}
