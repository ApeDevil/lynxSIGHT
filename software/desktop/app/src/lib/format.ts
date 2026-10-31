// Display texts for contract values. No calibration logic lives here.
import type { Guidance } from "./contracts/Guidance";
import type { Metric } from "./contracts/Metric";
import type { MetricSet } from "./contracts/MetricSet";
import type { Verdict } from "./contracts/Verdict";

export function metric(m: Metric | undefined, unit = "", digits = 1): string {
  if (!m) return "–";
  return m.status === "available" ? `${m.value.toFixed(digits)}${unit ? " " + unit : ""}` : "unknown";
}

/** "41.6 px · 9.7 mm · 0.82°", leaving out units the geometry cannot support. */
export function metricSet(s: MetricSet | undefined): string {
  if (!s) return "–";
  const parts = [];
  if (s.px.status === "available") parts.push(`${s.px.value.toFixed(1)} px`);
  if (s.mm.status === "available") parts.push(`${s.mm.value.toFixed(1)} mm`);
  if (s.deg.status === "available") parts.push(`${s.deg.value.toFixed(2)}°`);
  return parts.length ? parts.join(" · ") : "unknown";
}

export function why(m: Metric | undefined): string {
  return m && m.status === "unavailable" ? m.reason : "";
}

const GUIDANCE: Record<Guidance, string> = {
  face_not_found: "No face found: sit in front of the cameras",
  move_left: "Move a little to your left",
  move_right: "Move a little to your right",
  move_up: "Raise your head a little",
  move_down: "Lower your head a little",
  move_closer: "Move a little closer",
  move_back: "Move back a little",
  turn_toward_screen: "Face the screen",
  open_eyes: "Eyes closed or squinting",
  hold_still: "Hold still",
  good: "Position is good",
};

export function guidance(g: Guidance): string {
  return GUIDANCE[g];
}

const VERDICT: Record<Verdict, string> = {
  better: "better than the active calibration",
  equivalent: "about as good as the active calibration",
  worse: "worse than the active calibration",
  inconclusive: "too little validation data to compare",
};

export function verdict(v: Verdict): string {
  return VERDICT[v];
}
