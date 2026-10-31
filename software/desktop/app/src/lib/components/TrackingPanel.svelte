<script lang="ts">
  // Tracking quality, polled while visible. Quality only: says nothing about accuracy.
  import { onDestroy } from "svelte";
  import type { Backend } from "../backend";
  import type { TrackingStatus } from "../contracts/TrackingStatus";
  import { guidance, metric } from "../format";

  let { backend }: { backend: Backend } = $props();
  let status = $state<TrackingStatus | null>(null);
  let error = $state("");

  const timer = setInterval(async () => {
    try {
      status = await backend.tracking();
      error = "";
    } catch (e) {
      error = String(e);
    }
  }, 300);
  onDestroy(() => clearInterval(timer));
</script>

<section>
  <h2>Tracking quality</h2>
  {#if error}
    <p class="bad">{error}</p>
  {:else if !status}
    <p class="muted">waiting for the engine…</p>
  {:else}
    <p class={status.ready ? "good" : "warn"}>
      {status.ready ? "Ready: both eyes tracked" : "Not ready"} — {status.guidance.map(guidance).join(", ")}
    </p>
    <table>
      <thead><tr><th>camera</th><th>state</th><th>fps</th><th>face</th><th>eyes</th><th>head yaw / pitch</th><th>latency</th></tr></thead>
      <tbody>
        {#each status.cameras as cam (cam.camera_id)}
          <tr>
            <td>{cam.camera_id}</td>
            <td>{cam.state}</td>
            <td>{metric(cam.fps, "", 0)}</td>
            <td>{cam.face_detected ? metric(cam.face_confidence, "", 2) : "none"}</td>
            <td>{cam.eyes.map((e) => `${e.eye.replace("image_", "")}: ${e.state}`).join(", ")}</td>
            <td>
              {cam.head_pose ? `${cam.head_pose.yaw_deg.toFixed(0)}° / ${cam.head_pose.pitch_deg.toFixed(0)}° (uncalibrated)` : "–"}
            </td>
            <td>{metric(cam.pipeline_latency_ms, "ms", 0)}</td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
</section>
