<script lang="ts">
  // Profiles and the source to calibrate with. Physical sizes the user leaves empty stay
  // unknown (or EDID estimates); nothing here pretends to know them.
  import type { Backend } from "../backend";
  import type { AppStatus } from "../contracts/AppStatus";
  import type { Compatibility } from "../contracts/Compatibility";
  import type { ProfileSummary } from "../contracts/ProfileSummary";
  import type { SourceChoice } from "../contracts/SourceChoice";
  import type { Workflow } from "../contracts/Workflow";
  import { metricSet } from "../format";

  let {
    backend,
    status,
    onstart,
    onerror,
  }: {
    backend: Backend;
    status: AppStatus;
    onstart: (profileId: string, workflow: Workflow, source: SourceChoice) => void;
    onerror: (message: string) => void;
  } = $props();

  let profiles = $state<ProfileSummary[]>([]);
  let selected = $state<string | null>(null);
  let compat = $state<Compatibility | null>(null);

  let sourceKind = $state<"synthetic" | "cameras">("synthetic");
  let seed = $state(1);
  let experimentConfig = $state("software/diagnostic/exp.yaml");
  const source = $derived<SourceChoice>(
    sourceKind === "synthetic"
      ? { kind: "synthetic", seed, scenario: null }
      : { kind: "cameras", experiment_config: experimentConfig },
  );

  let name = $state("");
  let displayIndex = $state(0);
  let widthMm = $state<number | null>(null);
  let heightMm = $state<number | null>(null);
  let aboveMm = $state<number | null>(null);
  let behindMm = $state<number | null>(null);
  let distanceMm = $state<number | null>(null);

  const num = (v: number | null | undefined) => (typeof v === "number" && Number.isFinite(v) ? v : null);

  async function refresh() {
    try {
      profiles = await backend.listProfiles();
      if (selected && !profiles.some((p) => p.profile_id === selected)) selected = null;
    } catch (e) {
      onerror(String(e));
    }
  }

  async function create() {
    try {
      const p = await backend.createProfile(name || "default", {
        display_index: displayIndex,
        measured_width_mm: num(widthMm),
        measured_height_mm: num(heightMm),
        rig_above_screen_mm: num(aboveMm),
        screen_behind_rig_mm: num(behindMm),
        viewing_distance_mm: num(distanceMm),
      });
      await refresh();
      selected = p.profile_id;
    } catch (e) {
      onerror(String(e));
    }
  }

  async function remove(id: string) {
    if (!confirm("Delete this profile and its calibration history?")) return;
    try {
      await backend.deleteProfile(id);
      await refresh();
    } catch (e) {
      onerror(String(e));
    }
  }

  $effect(() => {
    const id = selected;
    const s = source;
    compat = null;
    if (!id) return;
    backend.compatibility(id, s).then(
      (c) => (compat = c),
      (e) => onerror(String(e)),
    );
  });

  const chosen = $derived(profiles.find((p) => p.profile_id === selected));
  refresh();
</script>

<section>
  <h2>Displays</h2>
  <table>
    <thead><tr><th>#</th><th>display</th><th>desktop position</th><th>mode</th><th>physical size</th></tr></thead>
    <tbody>
      {#each status.displays.displays as d, i (i)}
        <tr>
          <td>{i}</td>
          <td>{d.name}{d.primary ? " (primary)" : ""}</td>
          <td>{d.desktop.x}, {d.desktop.y} · {d.desktop.width}×{d.desktop.height}</td>
          <td>{d.mode.width}×{d.mode.height}{d.refresh_hz ? ` @ ${d.refresh_hz.toFixed(0)} Hz` : ""} · scale {d.scale_factor}</td>
          <td>
            {#if d.physical}{d.physical.width_mm.toFixed(0)}×{d.physical.height_mm.toFixed(0)} mm
              <span class="muted">({d.physical.provenance})</span>{:else}<span class="muted">unknown</span>{/if}
          </td>
        </tr>
      {/each}
    </tbody>
  </table>
  {#each status.displays.warnings as w (w)}<p class="warn">{w}</p>{/each}
  <button class="secondary" onclick={async () => (status = await backend.rediscoverDisplays())}>Rediscover</button>
</section>

<section>
  <h2>Source</h2>
  <label><input type="radio" bind:group={sourceKind} value="synthetic" /> Synthetic user (no cameras)</label>
  <label><input type="radio" bind:group={sourceKind} value="cameras" /> Cameras</label>
  {#if sourceKind === "synthetic"}
    <label>seed <input type="number" min="0" bind:value={seed} style="width: 6rem" /></label>
    <p class="muted">Results on the synthetic user test the software, not real accuracy.</p>
  {:else}
    <label>experiment config <input bind:value={experimentConfig} style="width: 24rem" /></label>
  {/if}
</section>

<section>
  <h2>Profiles</h2>
  {#if profiles.length === 0}<p class="muted">No profiles in {status.profile_dir}.</p>{/if}
  <table>
    <tbody>
      {#each profiles as p (p.profile_id)}
        <tr>
          <td><input type="radio" bind:group={selected} value={p.profile_id} disabled={!!p.problem} /></td>
          <td>{p.name ?? p.profile_id}</td>
          <td class="muted">{p.display_name ?? ""}</td>
          <td>
            {#if p.problem}<span class="bad">{p.problem}</span>
            {:else if p.has_model}calibrated · {metricSet(p.active_validation?.accuracy?.median)} median
            {:else}<span class="muted">not calibrated</span>{/if}
          </td>
          <td><button class="danger" onclick={() => remove(p.profile_id)}>Delete</button></td>
        </tr>
      {/each}
    </tbody>
  </table>

  {#if chosen}
    {#if compat}
      <p class={compat.status === "compatible" ? "good" : compat.status === "incompatible" ? "bad" : "warn"}>
        {compat.status.replaceAll("_", " ")}{compat.reasons.length ? ": " + compat.reasons.join("; ") : ""}
      </p>
    {/if}
    <div class="row">
      <button onclick={() => onstart(chosen.profile_id, "full", source)}>Full calibration</button>
      <button class="secondary" disabled={!chosen.has_model} onclick={() => onstart(chosen.profile_id, "quick", source)}>
        Quick recalibration
      </button>
    </div>
  {/if}

  <h2>New profile</h2>
  <div>
    <label>name <input bind:value={name} placeholder="default" /></label>
    <label>
      display
      <select bind:value={displayIndex}>
        {#each status.displays.displays as d, i (i)}<option value={i}>{d.name}</option>{/each}
      </select>
    </label>
  </div>
  <div>
    <label>measured width mm <input type="number" bind:value={widthMm} style="width: 6rem" /></label>
    <label>height mm <input type="number" bind:value={heightMm} style="width: 6rem" /></label>
  </div>
  <div>
    <label>rig above screen top mm <input type="number" bind:value={aboveMm} style="width: 6rem" /></label>
    <label>screen behind rig mm <input type="number" bind:value={behindMm} style="width: 6rem" /></label>
    <label>viewing distance mm <input type="number" bind:value={distanceMm} style="width: 6rem" /></label>
  </div>
  <p class="muted">Leave a value empty when it is not measured: it then stays unknown and no metric pretends otherwise.</p>
  <button onclick={create} disabled={status.displays.displays.length === 0}>Create profile</button>
</section>
