<script lang="ts">
  // The candidate, its validation and (for recalibration) the comparison with the active
  // model. Accepting is the core's decision to install or ask first; nothing is replaced silently.
  import type { Candidate } from "../contracts/Candidate";
  import type { ValidationReport } from "../contracts/ValidationReport";
  import { metric, metricSet, verdict, why } from "../format";
  import Heatmap from "./Heatmap.svelte";

  let {
    candidate,
    onaccept,
    ondecline,
  }: { candidate: Candidate; onaccept: (confirmed: boolean) => void; ondecline: () => void } = $props();
  let confirmed = $state(false);
  const report: ValidationReport = $derived(candidate.validation);
</script>

<section>
  <h2>Review</h2>
  {#if candidate.comparison}
    <p class={candidate.comparison.verdict === "better" ? "good" : "warn"}>
      The new calibration is {verdict(candidate.comparison.verdict)}: {candidate.comparison.reason}
    </p>
  {/if}
  {#if report.accuracy}
    <table>
      <tbody>
        <tr><td>median error</td><td>{metricSet(report.accuracy.median)}</td></tr>
        <tr><td>RMS</td><td>{metricSet(report.accuracy.rms)}</td></tr>
        <tr><td>90th percentile</td><td>{metricSet(report.accuracy.p90)}</td></tr>
        <tr><td>bias x / y</td><td>{metricSet(report.accuracy.bias_x)} / {metricSet(report.accuracy.bias_y)}</td></tr>
        <tr><td>validation</td><td>{report.targets} targets, {report.samples} samples</td></tr>
        <tr>
          <td>accepted samples</td>
          <td>{metric(report.acceptance.acceptance_rate, "", 2)} ({report.acceptance.accepted}/{report.acceptance.total})</td>
        </tr>
        <tr><td>latency</td><td>{metric(report.latency_ms, "ms", 0)} <span class="muted">{why(report.latency_ms)}</span></td></tr>
      </tbody>
    </table>
    <p class="muted">Millimetres and degrees appear only when the display size and screen pose are measured.</p>
    <Heatmap {report} />
  {:else}
    <p class="warn">No validation data: the accuracy of this calibration is unknown.</p>
  {/if}
  {#if candidate.fit}
    <p class="muted">
      Training: {candidate.fit.training.targets} targets, {candidate.fit.training.samples} samples, RMS
      {metric(candidate.fit.training.train_rms_px, "px")}, leave-one-target-out RMS
      {metric(candidate.fit.training.leave_one_out_rms_px, "px")} (fit data, not validation).
    </p>
  {/if}

  {#if candidate.acceptance.decision === "confirm_first"}
    <p class="warn">{candidate.acceptance.reason}</p>
    <label><input type="checkbox" bind:checked={confirmed} /> Install anyway</label>
  {/if}
  <div class="row">
    <button disabled={candidate.acceptance.decision === "confirm_first" && !confirmed} onclick={() => onaccept(confirmed)}>
      Accept
    </button>
    <button class="secondary" onclick={ondecline}>Decline (keep the active calibration)</button>
  </div>
</section>
