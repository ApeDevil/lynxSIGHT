<script lang="ts">
  // One face/eye baseline stage: instruction, a short countdown, then a timed capture.
  // The baseline is in image space only; it identifies no one.
  import type { Backend } from "../backend";
  import type { BaselineStage } from "../contracts/BaselineStage";
  import type { BaselineStageResult } from "../contracts/BaselineStageResult";

  let {
    backend,
    stage,
    ondone,
    onerror,
  }: {
    backend: Backend;
    stage: BaselineStage;
    ondone: (r: BaselineStageResult) => void;
    onerror: (message: string) => void;
  } = $props();

  const TEXT: Record<BaselineStage, { title: string; how: string; seconds: number }> = {
    detect_stable: { title: "Find your face", how: "Sit as you normally would and look at the screen.", seconds: 3 },
    neutral: { title: "Neutral pose", how: "Look at the centre of the screen, keep your head still, blink normally.", seconds: 4 },
    pose_range: {
      title: "Comfortable range",
      how: "Slowly turn and tilt your head a little in every direction you would while working.",
      seconds: 6,
    },
  };
  const info = $derived(TEXT[stage]);
  let remaining = $state<number | null>(null);
  let result = $state<BaselineStageResult | null>(null);

  async function capture() {
    result = null;
    remaining = info.seconds;
    const start = performance.now();
    const tick = setInterval(() => (remaining = Math.max(0, info.seconds - Math.floor((performance.now() - start) / 1000))), 200);
    await new Promise((r) => setTimeout(r, info.seconds * 1000));
    clearInterval(tick);
    remaining = null;
    try {
      result = await backend.captureBaseline(stage, start, performance.now());
      if (result.ok) ondone(result);
    } catch (e) {
      onerror(String(e));
    }
  }
</script>

<section>
  <h2>Baseline: {info.title}</h2>
  <p>{info.how}</p>
  {#if remaining !== null}
    <p class="good">Capturing… {remaining} s</p>
  {:else}
    <button onclick={capture}>{result && !result.ok ? "Try again" : "Start"}</button>
  {/if}
  {#if result}
    <p class={result.ok ? "good" : "warn"}>{result.message} ({result.accepted}/{result.samples} samples)</p>
  {/if}
</section>
