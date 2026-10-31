// Contract values for the UI tests.
import type { MetricSet } from "./contracts/MetricSet";
import type { ValidationReport } from "./contracts/ValidationReport";

export const unknown = { status: "unavailable" as const, reason: "physical display size unknown" };
export const px = (v: number): MetricSet => ({ px: { status: "available", value: v }, mm: unknown, deg: unknown });

export const report: ValidationReport = {
  source: "independent",
  targets: 3,
  samples: 90,
  accuracy: { median: px(30), rms: px(40), p90: px(60), bias_x: px(5), bias_y: px(-2) },
  region_cols: 3,
  region_rows: 3,
  regions: [
    { col: 0, row: 0, samples: 30, median: px(20) },
    { col: 2, row: 0, samples: 30, median: px(60) },
    { col: 1, row: 1, samples: 30, median: px(40) },
  ],
  acceptance: { total: 120, accepted: 90, rejected: { missing: 0, low_confidence: 0, blink: 30, unstable: 0, not_following: 0, settling: 0, outside_presentation: 0 }, acceptance_rate: { status: "available", value: 0.75 } },
  latency_ms: { status: "unavailable", reason: "no pursuit" },
};

