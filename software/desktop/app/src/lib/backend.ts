// The desktop core's commands (src-tauri/src/commands.rs). Every type comes from the
// generated contracts. Outside the Tauri shell there is no backend: the UI says so.
import type { AppStatus } from "./contracts/AppStatus";
import type { BaselineStage } from "./contracts/BaselineStage";
import type { BaselineStageResult } from "./contracts/BaselineStageResult";
import type { CollectionSummary } from "./contracts/CollectionSummary";
import type { Compatibility } from "./contracts/Compatibility";
import type { DisplaySetup } from "./contracts/DisplaySetup";
import type { ProfileSummary } from "./contracts/ProfileSummary";
import type { SessionView } from "./contracts/SessionView";
import type { SourceChoice } from "./contracts/SourceChoice";
import type { TargetPlan } from "./contracts/TargetPlan";
import type { TrackingStatus } from "./contracts/TrackingStatus";
import type { UiPresentation } from "./contracts/UiPresentation";
import type { Workflow } from "./contracts/Workflow";

export interface Backend {
  status(): Promise<AppStatus>;
  rediscoverDisplays(): Promise<AppStatus>;
  listProfiles(): Promise<ProfileSummary[]>;
  createProfile(name: string, setup: DisplaySetup): Promise<ProfileSummary>;
  deleteProfile(profileId: string): Promise<void>;
  compatibility(profileId: string, source: SourceChoice): Promise<Compatibility>;
  startSession(profileId: string, workflow: Workflow, source: SourceChoice): Promise<SessionView>;
  endSession(): Promise<void>;
  session(): Promise<SessionView | null>;
  tracking(): Promise<TrackingStatus>;
  syncClock(uiNowMs: number): Promise<void>;
  captureBaseline(stage: BaselineStage, startMs: number, endMs: number): Promise<BaselineStageResult>;
  plan(): Promise<TargetPlan>;
  submit(presentation: UiPresentation): Promise<CollectionSummary>;
  restartStep(): Promise<SessionView>;
  skipStep(): Promise<SessionView>;
  redo(index: number): Promise<SessionView>;
  runModelStep(): Promise<SessionView>;
  accept(confirmed: boolean): Promise<SessionView>;
  decline(): Promise<SessionView>;
  setFullscreen(on: boolean): Promise<void>;
}

type Invoke = <T>(cmd: string, args?: Record<string, unknown>) => Promise<T>;

export function inTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

export function tauriBackend(invoke: Invoke, fullscreen: (on: boolean) => Promise<void>): Backend {
  return {
    status: () => invoke("status"),
    rediscoverDisplays: () => invoke("rediscover_displays"),
    listProfiles: () => invoke("list_profiles"),
    createProfile: (name, setup) => invoke("create_profile", { name, setup }),
    deleteProfile: (profileId) => invoke("delete_profile", { profileId }),
    compatibility: (profileId, source) => invoke("compatibility", { profileId, source }),
    startSession: (profileId, workflow, source) => invoke("start_session", { profileId, workflow, source }),
    endSession: () => invoke("end_session"),
    session: () => invoke("session"),
    tracking: () => invoke("tracking"),
    syncClock: (uiNowMs) => invoke("sync_clock", { uiNowMs }),
    captureBaseline: (stage, startMs, endMs) => invoke("capture_baseline", { stage, startMs, endMs }),
    plan: () => invoke("plan"),
    submit: (presentation) => invoke("submit", { presentation }),
    restartStep: () => invoke("restart_step"),
    skipStep: () => invoke("skip_step"),
    redo: (index) => invoke("redo", { index }),
    runModelStep: () => invoke("run_model_step"),
    accept: (confirmed) => invoke("accept", { confirmed }),
    decline: () => invoke("decline"),
    setFullscreen: fullscreen,
  };
}

/** Ten round trips; the core keeps the fastest (see `clock::UiClock`). */
export async function syncClock(backend: Backend, rounds = 10): Promise<void> {
  for (let i = 0; i < rounds; i++) await backend.syncClock(performance.now());
}

export async function connect(): Promise<Backend | null> {
  if (!inTauri()) return null;
  const { invoke } = await import("@tauri-apps/api/core");
  const { getCurrentWindow } = await import("@tauri-apps/api/window");
  return tauriBackend(invoke, (on) => getCurrentWindow().setFullscreen(on));
}
