# Pointer integration (milestone 5: dry run only)

Status: contract and policy implemented, **no pointer is moved**. The dry-run backend
(`software/desktop/crates/session/src/pointer.rs`) records what a real backend would do. No V4
firmware, no uinput device and no LYNX Bridge exist on this side yet.

## What exists

* Contract `PointerIntent` (`crates/contracts/src/pointer.rs`, schema
  `contracts/schemas/pointer-intent.v1.schema.json`): mode, tracking state, display and
  normalized target, desktop target, confidence, observed cursor, and the action.
* `pointer::intent(mode, policy, layout, inputs)`: the one place that turns a gaze estimate into
  an action. Desktop coordinates come from the geometry crate, so negative offsets and mixed
  scale factors are handled once.
* `DryRunBackend`: appends intents to a log for visualisation and tests.

## Policy

| Mode | Behaviour | Default |
|---|---|---|
| `manual` | gaze ignored | **on** |
| `gaze_assisted` | one warp to the gaze target when the user presses an activation key, only with a fresh (< 150 ms) and confident (≥ 0.6) estimate, never within 500 ms of manual pointer input | off |
| `hands_free` | research only; in this backend it behaves like `gaze_assisted` | off |

Gaze never clicks. Manual input always wins (`manual_override`). A stale or lost estimate yields
no action. The thresholds are `PointerPolicy::default()` and are provisional until measured on
hardware (latency and accuracy from the validation report).

## Recommendations for the LYNX Bridge and the V4 Coordinator

These are proposals; nothing here changes `lynx-v4`.

1. **Keep gaze on the host.** The Coordinator should not interpret gaze. The desktop core owns
   the display layout, the calibration and the policy above; what crosses to V4 (if anything)
   is a finished pointer action, not gaze data. This keeps the V4 rule "cats capture; the
   Coordinator interprets" intact: SIGHT is a capture-and-interpret device on the host side.
2. **Prefer a host backend first.** A Linux `uinput` absolute-pointer backend in the desktop
   core is the shortest path to a test and needs no firmware. Only if the pointer must come
   from the keyboard's USB device (one HID device for the user, works without host software
   for the movement itself) should the Bridge send actions to the Coordinator.
3. **If actions do go to V4,** define one versioned, append-only message (in the spirit of the
   V4 protocol's postcard enums): `Warp { display, x, y }` in normalized display coordinates
   plus the display's desktop rectangle, or an absolute HID report the Coordinator forwards
   unchanged. The Coordinator would add a digitizer/absolute-pointer HID interface; relative
   mouse reports cannot express a warp reliably across scaling and acceleration.
4. **The activation key belongs to the keymap.** A V4 binding (a layer key or a dedicated key)
   that reports "activation pressed" to the host is the natural trigger for gaze-assisted
   warps; manual pointer motion from the V4 trackball/trackpoint feeds the manual-override
   window. Both are inputs to `pointer::intent`, which stays the single decision point.
5. **Latency budget.** Report end-to-end latency from the validation report alongside any
   pointer test; a warp on a stale estimate is worse than none.

Open questions for the user: whether SIGHT input should ever reach the host through V4's USB
device, and which key acts as the activation key.
