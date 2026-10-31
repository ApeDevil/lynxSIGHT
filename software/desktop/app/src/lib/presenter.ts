// Presentation of a target plan: where the target is at a given plan time, and a recorder of
// what was actually drawn when. Target positions and paths come from the engine; this module
// only interpolates the sampled path linearly between samples, which is all drawing needs.
import type { NormPoint } from "./contracts/NormPoint";
import type { TargetPlan } from "./contracts/TargetPlan";
import type { UiFrame } from "./contracts/UiFrame";
import type { UiPresentation } from "./contracts/UiPresentation";
import type { UiSpan } from "./contracts/UiSpan";

export interface TargetState {
  position: NormPoint;
  targetIndex: number | null;
  /** For stationary targets: true while samples count (after the settle time). */
  collecting: boolean;
  finished: boolean;
}

export function targetAt(plan: TargetPlan, planMs: number): TargetState {
  const finished = planMs >= plan.duration_ms;
  const body = plan.body;
  if (body.method === "stationary") {
    const per = body.settle_ms + body.dwell_ms;
    const i = Math.min(Math.max(Math.floor(planMs / per), 0), body.targets.length - 1);
    const target = body.targets[i]!;
    const into = planMs - i * per;
    return { position: target.position, targetIndex: target.index, collecting: into >= body.settle_ms, finished };
  }
  const path = body.path;
  if (planMs <= path[0]!.t_ms) return { position: path[0]!.position, targetIndex: null, collecting: false, finished };
  const last = path[path.length - 1]!;
  if (planMs >= last.t_ms) return { position: last.position, targetIndex: null, collecting: true, finished };
  // Binary search for the segment containing planMs.
  let lo = 0;
  let hi = path.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (path[mid]!.t_ms <= planMs) lo = mid;
    else hi = mid;
  }
  const a = path[lo]!;
  const b = path[hi]!;
  const f = (planMs - a.t_ms) / (b.t_ms - a.t_ms);
  const position = { x: a.position.x + f * (b.position.x - a.position.x), y: a.position.y + f * (b.position.y - a.position.y) };
  return { position, targetIndex: null, collecting: planMs >= body.lead_in_ms, finished };
}

/**
 * Advances plan time with the frame clock, stops it while paused, and records every drawn
 * frame. Times are `performance.now()` milliseconds (the core maps them to CLOCK_MONOTONIC).
 */
export class PresentationRecorder {
  private frames: UiFrame[] = [];
  private spans: UiSpan[] = [];
  private spanStart: number | null = null;
  private lastFrame: number | null = null;
  private planMs = 0;
  paused = false;

  constructor(readonly plan: TargetPlan) {}

  get time(): number {
    return this.planMs;
  }

  /** Called once per displayed frame with its timestamp; returns what to draw. */
  frame(nowMs: number): TargetState {
    if (this.paused) {
      return { ...targetAt(this.plan, this.planMs), collecting: false };
    }
    if (this.spanStart === null) this.spanStart = nowMs;
    if (this.lastFrame !== null) this.planMs += nowMs - this.lastFrame;
    this.lastFrame = nowMs;
    const state = targetAt(this.plan, this.planMs);
    if (!state.finished) this.frames.push({ t_ms: nowMs, position: state.position, target_index: state.targetIndex });
    return state;
  }

  pause(nowMs: number): void {
    if (this.paused) return;
    this.closeSpan(nowMs);
    this.paused = true;
  }

  resume(): void {
    this.paused = false;
  }

  private closeSpan(nowMs: number): void {
    if (this.spanStart !== null) this.spans.push({ start_ms: this.spanStart, end_ms: nowMs });
    this.spanStart = null;
    this.lastFrame = null;
  }

  /** The record of what was shown; `completed` is false when the user skipped ahead. */
  finish(nowMs: number, completed: boolean, backgroundBrightness: number): UiPresentation {
    this.closeSpan(nowMs);
    return { plan_id: this.plan.plan_id, frames: this.frames, spans: this.spans, completed, background_brightness: backgroundBrightness };
  }
}
