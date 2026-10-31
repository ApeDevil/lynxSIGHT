<script lang="ts">
  // Fullscreen target presentation. Draws what the plan says and records what it drew;
  // Space pauses, R restarts, S skips the rest, Esc cancels.
  import { onDestroy, onMount } from "svelte";
  import type { TargetPlan } from "../contracts/TargetPlan";
  import type { UiPresentation } from "../contracts/UiPresentation";
  import { PresentationRecorder } from "../presenter";

  let {
    plan,
    brightness = 0.15,
    ondone,
    onrestart,
    oncancel,
  }: {
    plan: TargetPlan;
    brightness?: number;
    ondone: (p: UiPresentation) => void;
    onrestart: () => void;
    oncancel: () => void;
  } = $props();

  let canvas: HTMLCanvasElement;
  let recorder: PresentationRecorder;
  let raf = 0;
  let paused = $state(false);
  let level = $state(0.15);
  let ended = false;
  // The help line covers edge targets: it shows for the first seconds and while paused.
  let showHelp = $state(true);
  const helpTimer = setTimeout(() => (showHelp = false), 3000);
  const instruction = $derived(
    plan.body.method === "pursuit" ? "Follow the moving dot with your eyes" : "Look at each dot until it moves on",
  );

  function draw(now: number) {
    const ctx = canvas.getContext("2d")!;
    const w = (canvas.width = canvas.clientWidth * devicePixelRatio);
    const h = (canvas.height = canvas.clientHeight * devicePixelRatio);
    const state = recorder.frame(now);
    const grey = Math.round(level * 255);
    ctx.fillStyle = `rgb(${grey},${grey},${grey})`;
    ctx.fillRect(0, 0, w, h);
    if (state.finished) return finish(true, now);
    const x = state.position.x * w;
    const y = state.position.y * h;
    const r = Math.min(w, h) * 0.018;
    // High contrast whatever the background: white ring on a black disc, a small centre dot.
    ctx.beginPath();
    ctx.arc(x, y, r * 1.3, 0, 2 * Math.PI);
    ctx.fillStyle = "black";
    ctx.fill();
    ctx.beginPath();
    ctx.arc(x, y, r, 0, 2 * Math.PI);
    ctx.lineWidth = r * 0.25;
    ctx.strokeStyle = paused ? "#888" : state.collecting ? "white" : "#f0b400";
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(x, y, r * 0.15, 0, 2 * Math.PI);
    ctx.fillStyle = "white";
    ctx.fill();
    raf = requestAnimationFrame(draw);
  }

  function finish(completed: boolean, now = performance.now()) {
    if (ended) return;
    ended = true;
    cancelAnimationFrame(raf);
    ondone(recorder.finish(now, completed, level));
  }

  function key(e: KeyboardEvent) {
    if (e.key === " ") {
      e.preventDefault();
      if (recorder.paused) recorder.resume();
      else recorder.pause(performance.now());
      paused = recorder.paused;
    } else if (e.key === "s" || e.key === "S") finish(false);
    else if (e.key === "r" || e.key === "R") {
      ended = true;
      cancelAnimationFrame(raf);
      onrestart();
    } else if (e.key === "Escape") {
      ended = true;
      cancelAnimationFrame(raf);
      oncancel();
    } else if (e.key === "+" || e.key === "=") level = Math.min(1, level + 0.05);
    else if (e.key === "-") level = Math.max(0, level - 0.05);
  }

  onMount(() => {
    level = brightness;
    recorder = new PresentationRecorder(plan);
    raf = requestAnimationFrame(draw);
  });
  onDestroy(() => {
    cancelAnimationFrame(raf);
    clearTimeout(helpTimer);
  });
</script>

<svelte:window onkeydown={key} />
<div class="stage">
  <canvas bind:this={canvas}></canvas>
  {#if showHelp || paused}
    <p class="help">
      {paused ? "Paused — Space resumes" : `${instruction}, keep your head still`} · Space pause · R restart · S skip · Esc
      cancel · +/- background
    </p>
  {/if}
</div>

<style>
  .stage { position: fixed; inset: 0; z-index: 10; background: black; cursor: none; }
  canvas { width: 100%; height: 100%; display: block; }
  .help { position: absolute; bottom: 0.5rem; width: 100%; text-align: center; color: #777; font-size: 0.85rem; margin: 0; }
</style>
