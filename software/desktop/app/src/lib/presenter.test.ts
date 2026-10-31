import { describe, expect, it } from "vitest";
import type { TargetPlan } from "./contracts/TargetPlan";
import { PresentationRecorder, targetAt } from "./presenter";

const stationary: TargetPlan = {
  plan_id: "s",
  purpose: "fit",
  duration_ms: 3000,
  body: {
    method: "stationary",
    settle_ms: 500,
    dwell_ms: 1000,
    targets: [
      { index: 0, position: { x: 0.5, y: 0.5 } },
      { index: 1, position: { x: 0.1, y: 0.1 } },
    ],
  },
};

const pursuit: TargetPlan = {
  plan_id: "p",
  purpose: "fit",
  duration_ms: 2000,
  body: {
    method: "pursuit",
    lead_in_ms: 1000,
    trajectory: { trajectory: "perimeter", margin: 0.1 },
    path: [
      { t_ms: 0, position: { x: 0.1, y: 0.1 } },
      { t_ms: 1000, position: { x: 0.1, y: 0.1 } },
      { t_ms: 2000, position: { x: 0.9, y: 0.1 } },
    ],
  },
};

describe("targetAt", () => {
  it("steps through stationary targets and marks the settle time", () => {
    expect(targetAt(stationary, 100)).toMatchObject({ targetIndex: 0, collecting: false });
    expect(targetAt(stationary, 600)).toMatchObject({ targetIndex: 0, collecting: true });
    expect(targetAt(stationary, 1600)).toMatchObject({ targetIndex: 1, collecting: false, position: { x: 0.1, y: 0.1 } });
    expect(targetAt(stationary, 3000).finished).toBe(true);
  });

  it("interpolates the pursuit path linearly after the lead-in", () => {
    expect(targetAt(pursuit, 500)).toMatchObject({ collecting: false, position: { x: 0.1, y: 0.1 } });
    const mid = targetAt(pursuit, 1500);
    expect(mid.position.x).toBeCloseTo(0.5);
    expect(mid.collecting).toBe(true);
    expect(targetAt(pursuit, 2500)).toMatchObject({ finished: true, position: { x: 0.9, y: 0.1 } });
  });
});

describe("PresentationRecorder", () => {
  it("records drawn frames and splits spans at pauses without advancing plan time", () => {
    const r = new PresentationRecorder(stationary);
    r.frame(1000);
    r.frame(1500);
    r.pause(1600);
    expect(r.frame(5000).collecting).toBe(false); // paused: nothing recorded
    r.resume();
    r.frame(6000);
    r.frame(6400);
    expect(r.time).toBeCloseTo(900);
    const p = r.finish(6500, false, 0.2);
    expect(p.spans).toEqual([
      { start_ms: 1000, end_ms: 1600 },
      { start_ms: 6000, end_ms: 6500 },
    ]);
    expect(p.frames.map((f) => f.t_ms)).toEqual([1000, 1500, 6000, 6400]);
    expect(p.completed).toBe(false);
    expect(p.background_brightness).toBe(0.2);
  });

  it("stops recording once the plan is over", () => {
    const r = new PresentationRecorder(pursuit);
    for (let t = 0; t <= 3000; t += 100) r.frame(t);
    const p = r.finish(3000, true, 0);
    expect(p.frames.length).toBe(20);
  });
});
