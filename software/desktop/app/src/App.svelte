<script lang="ts">
  // The calibration app: setup, then the session's steps as the core lists them. The core
  // (Rust) owns the workflow and every decision; this UI presents and reports.
  import { connect, syncClock, type Backend } from "./lib/backend";
  import type { AppStatus } from "./lib/contracts/AppStatus";
  import type { SessionView } from "./lib/contracts/SessionView";
  import type { SourceChoice } from "./lib/contracts/SourceChoice";
  import type { Step } from "./lib/contracts/Step";
  import type { TargetPlan } from "./lib/contracts/TargetPlan";
  import type { UiPresentation } from "./lib/contracts/UiPresentation";
  import type { Workflow } from "./lib/contracts/Workflow";
  import { metric } from "./lib/format";
  import BaselineStep from "./lib/components/BaselineStep.svelte";
  import Presenter from "./lib/components/Presenter.svelte";
  import Review from "./lib/components/Review.svelte";
  import Setup from "./lib/components/Setup.svelte";
  import TrackingPanel from "./lib/components/TrackingPanel.svelte";

  let backend = $state<Backend | null>(null);
  let connecting = $state(true);
  let status = $state<AppStatus | null>(null);
  let view = $state<SessionView | null>(null);
  let presenting = $state<TargetPlan | null>(null);
  let brightness = $state(0.15);
  let busy = $state(false);
  let error = $state("");

  connect().then(async (b) => {
    backend = b;
    connecting = false;
    if (!b) return;
    try {
      status = await b.status();
      view = await b.session();
    } catch (e) {
      error = String(e);
    }
  });

  const current = $derived<Step | null>(view && view.current < view.steps.length ? view.steps[view.current]!.step : null);

  function stepLabel(step: Step): string {
    switch (step.kind) {
      case "baseline":
        return `Baseline: ${step.stage.replaceAll("_", " ")}`;
      case "collect":
        return step.label;
      case "fit":
        return "Fit the model";
      case "recalibrate":
        return "Fit the correction";
      case "review":
        return "Review";
    }
  }

  async function run(action: () => Promise<SessionView | null | void>) {
    if (!backend || busy) return;
    busy = true;
    error = "";
    try {
      const v = await action();
      view = v === undefined ? await backend.session() : v;
    } catch (e) {
      error = String(e);
    } finally {
      busy = false;
    }
  }

  const start = (profileId: string, workflow: Workflow, source: SourceChoice) =>
    run(async () => {
      const v = await backend!.startSession(profileId, workflow, source);
      await syncClock(backend!);
      return v;
    });

  async function present() {
    if (!backend) return;
    try {
      await syncClock(backend);
      const plan = await backend.plan();
      await backend.setFullscreen(true);
      presenting = plan;
    } catch (e) {
      error = String(e);
    }
  }

  async function presented(p: UiPresentation) {
    presenting = null;
    brightness = p.background_brightness;
    await backend!.setFullscreen(false).catch(() => {});
    await run(async () => {
      await syncClock(backend!);
      await backend!.submit(p);
    });
  }

  async function leavePresentation(restart: boolean) {
    presenting = null;
    await backend!.setFullscreen(false).catch(() => {});
    if (restart) await run(() => backend!.restartStep()).then(present);
  }

  async function finish() {
    await run(async () => {
      await backend!.endSession();
      return null;
    });
    view = null;
  }
</script>

{#if presenting}
  <Presenter
    plan={presenting}
    {brightness}
    ondone={presented}
    onrestart={() => leavePresentation(true)}
    oncancel={() => leavePresentation(false)}
  />
{/if}

<main>
  <h1>LYNX SIGHT calibration</h1>
  {#if connecting}
    <p class="muted">Connecting…</p>
  {:else if !backend}
    <section>
      <p class="warn">No desktop core: this page runs inside the Tauri app.</p>
      <p>Start it with <code>npm run tauri dev</code> in <code>software/desktop/app</code>. The synthetic user needs no cameras.</p>
    </section>
  {:else if status}
    {#if status.engine.state === "unavailable"}
      <p class="bad">Vision engine unavailable: {status.engine.reason}</p>
    {/if}
    {#if error}<p class="bad">{error}</p>{/if}

    {#if !view}
      <Setup {backend} {status} onstart={start} onerror={(m) => (error = m)} />
    {:else}
      <section>
        <div class="row">
          <strong>{view.workflow === "full" ? "Full calibration" : "Quick recalibration"}</strong>
          {#if view.synthetic}<span class="warn">synthetic user: software test, not a measurement</span>{/if}
          <span class="muted">features {view.feature_set}</span>
          <span style="flex: 1"></span>
          <button class="secondary" onclick={finish}>{view.current >= view.steps.length ? "Done" : "Cancel"}</button>
        </div>
        <ol>
          {#each view.steps as s, i (i)}
            <li class={i === view.current ? "" : "muted"}>
              {stepLabel(s.step)}
              {#if s.skipped}(skipped){:else if s.done}✓{/if}
              {#if s.collection}
                · {s.collection.samples_accepted}/{s.collection.samples_total} samples
                {#if s.collection.targets_total !== null}· {s.collection.targets_usable}/{s.collection.targets_total} targets{/if}
                {#if s.collection.estimated_lag_ms.status === "available"}· lag {metric(s.collection.estimated_lag_ms, "ms", 0)}{/if}
                {#if s.collection.following_fraction.status === "available"}
                  · followed {metric(s.collection.following_fraction, "", 2)}
                {/if}
                {#each s.collection.warnings as w (w)}<span class="warn"> · {w}</span>{/each}
              {/if}
              {#if (s.done || s.skipped) && s.step.kind === "collect" && i < view.current && view.current < view.steps.length}
                <button class="secondary" onclick={() => run(() => backend!.redo(i))}>Redo</button>
              {/if}
            </li>
          {/each}
        </ol>
        {#if view.message}<p>{view.message}</p>{/if}
      </section>

      {#if current?.kind === "baseline"}
        <BaselineStep
          {backend}
          stage={current.stage}
          ondone={() => run(async () => {})}
          onerror={(m) => (error = m)}
        />
        <TrackingPanel {backend} />
      {:else if current?.kind === "collect"}
        <section>
          <h2>{current.label}</h2>
          <p>
            {current.request.method === "pursuit"
              ? "Follow the moving dot with your eyes."
              : "Look at each dot until it changes."} Keep your head still. The presentation is fullscreen.
          </p>
          <label>
            background <input type="range" min="0" max="1" step="0.05" bind:value={brightness} />
            {Math.round(brightness * 100)} %
          </label>
          <div class="row">
            <button onclick={present} disabled={busy}>Start</button>
            <button class="secondary" onclick={() => run(() => backend!.skipStep())} disabled={busy}>Skip</button>
          </div>
        </section>
        <TrackingPanel {backend} />
      {:else if current?.kind === "fit" || current?.kind === "recalibrate"}
        <section>
          <button onclick={() => run(() => backend!.runModelStep())} disabled={busy}>
            {busy ? "Fitting…" : stepLabel(current)}
          </button>
        </section>
      {:else if current?.kind === "review" && view.candidate}
        <Review
          candidate={view.candidate}
          onaccept={(c) => run(() => backend!.accept(c))}
          ondecline={() => run(() => backend!.decline())}
        />
      {:else if !current}
        <section><p class="good">Finished. {view.message ?? ""}</p></section>
      {/if}
    {/if}
  {/if}
</main>
