<script lang="ts">
  import type { ValidationReport } from "../contracts/ValidationReport";
  import { bestUnit, cells, colour } from "../heatmap";

  let { report }: { report: ValidationReport } = $props();
  const unit = $derived(bestUnit(report));
  const grid = $derived(cells(report, unit));
  const label = { px: "px", mm: "mm", deg: "°" };
</script>

<div class="grid" style="grid-template-columns: repeat({report.region_cols}, 1fr)" aria-label="error per screen region">
  {#each grid as c (`${c.col}-${c.row}`)}
    <div class="cell" style="background: {colour(c.shade)}" title="{c.samples} samples">
      {c.value === null ? "no data" : `${c.value.toFixed(unit === "deg" ? 2 : 0)} ${label[unit]}`}
    </div>
  {/each}
</div>

<style>
  .grid { display: grid; gap: 2px; aspect-ratio: 16 / 9; max-width: 480px; }
  .cell { display: flex; align-items: center; justify-content: center; font-size: 0.8rem; border-radius: 2px; }
</style>
