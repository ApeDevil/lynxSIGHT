"""Interactive and headless front ends on top of a `Session`."""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

import cv2
import numpy as np

from . import calibration, features, overlay
from .capture import State
from .config import CaptureSettings, ExperimentConfig, ProcessorConfig
from .processing.eyes import Eyes
from .processing.landmarks import Landmarks
from .recorder import Recorder, to_jsonable
from .session import Session

WINDOW = "LYNX SIGHT diagnostic"
DISPLAY_CONTROLS = ("auto_exposure", "exposure_time_absolute", "gain")
MANUAL_EXPOSURE = 1  # UVC auto_exposure menu: 1 = manual, 3 = aperture priority (auto)


# --- shared helpers ----------------------------------------------------------------------------


def start_recording(session: Session, raw_video: bool = False) -> Recorder:
    recorder = Recorder(session.config, raw_video=raw_video)
    for camera in session.cameras.values():
        camera.worker.observers.append(recorder.on_frame)
    session.board.listeners.append(recorder.on_result)
    negotiated = {}
    for cid, camera in session.cameras.items():
        source = camera.worker.source
        controls = source.controls
        negotiated[cid] = {
            "source": source.description,
            "negotiated": source.negotiated,
            "controls": {k: controls.get(k) for k in controls.available()} if controls else None,
            "control_errors": getattr(source, "control_errors", None),
        }
    recorder.write_config({"devices": negotiated})
    recorder.event("start")
    return recorder


def stop_recording(session: Session, recorder: Recorder) -> dict:
    for camera in session.cameras.values():
        if recorder.on_frame in camera.worker.observers:
            camera.worker.observers.remove(recorder.on_frame)
    if recorder.on_result in session.board.listeners:
        session.board.listeners.remove(recorder.on_result)
    return recorder.close()


def save_snapshot(session: Session, directory: Path, canvas: np.ndarray | None = None) -> Path:
    """Saves each camera's newest full-resolution frame as lossless PNG plus metadata."""
    stamp = time.strftime("%Y%m%d-%H%M%S") + f"-{int(time.time() * 1000) % 1000:03d}"
    target = directory / stamp
    target.mkdir(parents=True, exist_ok=True)
    meta: dict = {"experiment_id": session.config.experiment_id, "cameras": {}}
    for cid, camera in session.cameras.items():
        frame = camera.slot.latest()
        controls = camera.worker.source.controls
        entry = {
            "status": to_jsonable(camera.worker.status()),
            "controls": {k: controls.get(k) for k in controls.available()} if controls else None,
            "results": {
                name: to_jsonable(r.data)
                for (c, name), r in session.board.snapshot().items()
                if c == cid and r.data is not None
            },
        }
        if frame is not None:
            cv2.imwrite(str(target / f"{cid}.png"), frame.image)
            entry.update(seq=frame.seq, t_capture_ns=frame.t_capture_ns, format=frame.source_format)
        meta["cameras"][cid] = entry
    if canvas is not None:
        cv2.imwrite(str(target / "overlay.png"), canvas)
    (target / "snapshot.json").write_text(json.dumps(meta, indent=2, default=str))
    return target


def render(
    session: Session, selected: str, panel_width: int, show_overlays: bool, footer: str
) -> np.ndarray:
    panels, tiles = [], []
    board = session.board.snapshot()
    for cid, camera in session.cameras.items():
        frame = camera.slot.latest()
        results = {name: r for (c, name), r in board.items() if c == cid}
        # Only overlay results computed on the frame being shown or very recently, so stale
        # detections from before a disconnect don't linger.
        if frame is not None:
            results = {
                n: r
                for n, r in results.items()
                if frame.t_capture_ns - r.frame.t_capture_ns < 500e6
            }
        controls = camera.worker.source.controls
        values = {k: controls.get(k) for k in DISPLAY_CONTROLS} if controls else {}
        stats = {r.name: r.stats for r in camera.runners}
        image = frame.image if frame is not None else None
        panels.append(
            overlay.draw_panel(
                image,
                camera.worker.status(),
                results,
                stats,
                panel_width,
                values,
                cid == selected,
                show_overlays,
            )
        )
        eyes = results.get("eyes")
        # Tiles must be cut from the frame the eye regions were found in.
        landmarks = results.get("landmarks")
        iris = None
        close_in_time = (
            eyes
            and landmarks
            and abs(landmarks.frame.t_capture_ns - eyes.frame.t_capture_ns) < 100e6
        )
        if close_in_time and landmarks.data is not None:
            iris = landmarks.data.iris_centres
        tiles += overlay.eye_tiles(eyes.frame.image if eyes else None, eyes, iris)
    return overlay.compose(panels, tiles, footer)


# --- interactive viewer ------------------------------------------------------------------------


def run_viewer(
    session: Session,
    snapshot_dir: Path,
    panel_width: int = 640,
    phases: list[str] | None = None,
    raw_video: bool = False,
) -> None:
    phases = phases or []
    cv2.namedWindow(WINDOW, cv2.WINDOW_NORMAL)
    session.start()
    selected = next(iter(session.cameras))
    show_overlays = True
    paused = False
    recorder: Recorder | None = None
    message = "ready"
    sized = False
    try:
        while True:
            phase = recorder.phase if recorder else None
            footer = (
                f"{session.config.experiment_id} | "
                f"rec {'ON ' + str(recorder.run_dir) if recorder else 'off'}"
                f"{' | phase ' + phase if phase else ''} | {message}"
            )
            canvas = render(session, selected, panel_width, show_overlays, footer)
            cv2.imshow(WINDOW, canvas)
            if not sized:  # start at 1:1; the window stays resizable
                cv2.resizeWindow(WINDOW, canvas.shape[1], canvas.shape[0])
                sized = True
            key = cv2.waitKey(15) & 0xFF
            if cv2.getWindowProperty(WINDOW, cv2.WND_PROP_VISIBLE) < 1:
                break
            if key == 255:
                continue
            ch = chr(key)
            if ch in ("q", "\x1b"):
                break
            if ch == " ":
                paused = not paused
                session.pause() if paused else session.resume()
                message = "paused" if paused else "running"
            elif ch == "r":
                session.reconnect()
                message = "reconnecting all cameras"
            elif ch == "\t":
                ids = list(session.cameras)
                selected = ids[(ids.index(selected) + 1) % len(ids)]
                message = f"selected {selected}"
            elif ch == "s":
                message = f"snapshot -> {save_snapshot(session, snapshot_dir, canvas)}"
            elif ch == "o":
                show_overlays = not show_overlays
            elif ch in "[]":
                session.adjust_control(selected, "auto_exposure", value=MANUAL_EXPOSURE)
                ctl = session.cameras[selected].worker.source.controls
                cur = (ctl.get("exposure_time_absolute") if ctl else None) or 100
                target = max(1, round(cur / 1.25)) if ch == "[" else max(cur + 1, round(cur * 1.25))
                value, err = session.adjust_control(
                    selected, "exposure_time_absolute", value=target
                )
                message = err or f"{selected} exposure {value}"
            elif ch in "-=":
                value, err = session.adjust_control(selected, "gain", delta=-1 if ch == "-" else 1)
                message = err or f"{selected} gain {value}"
            elif ch == "a":
                ctl = session.cameras[selected].worker.source.controls
                manual = ctl is not None and ctl.get("auto_exposure") == MANUAL_EXPOSURE
                value, err = session.adjust_control(
                    selected, "auto_exposure", value=3 if manual else MANUAL_EXPOSURE
                )
                message = (
                    err or f"{selected} auto_exposure {value} ({'auto' if manual else 'manual'})"
                )
            elif ch == "R":
                if recorder:
                    summary = stop_recording(session, recorder)
                    message = f"recording saved: {recorder.run_dir} ({_short_summary(summary)})"
                    recorder = None
                else:
                    recorder = start_recording(session, raw_video)
                    message = "recording"
            elif ch.isdigit() and recorder:
                index = int(ch)
                name = (
                    None
                    if index == 0
                    else (phases[index - 1] if index <= len(phases) else f"p{index}")
                )
                recorder.set_phase(name)
                message = f"phase {name}"
            if recorder and ch in "[]-=a":
                recorder.event("control", camera_id=selected, message=message)
    finally:
        if recorder:
            stop_recording(session, recorder)
            print(f"recording saved: {recorder.run_dir}")
        session.stop()
        cv2.destroyAllWindows()


def _short_summary(summary: dict) -> str:
    parts = []
    for cid, cam in summary.get("cameras", {}).items():
        parts.append(f"{cid} {cam['fps']} fps, {cam['est_dropped']} drops~")
    return "; ".join(parts)


# --- headless ----------------------------------------------------------------------------------


def format_status_line(session: Session) -> str:
    parts = []
    for cid, st in session.status().items():
        fps = "-" if math.isnan(st.fps) else f"{st.fps:.1f}"
        err = f" ERR {st.error}" if st.state is State.ERROR else ""
        parts.append(
            f"{cid}: {st.state.value} {fps} fps, {st.frames} frames, {st.est_dropped} drops~{err}"
        )
    return " | ".join(parts)


def run_headless(
    session: Session,
    duration_s: float,
    phases: list[tuple[str, float]] | None = None,
    raw_video: bool = False,
    warmup_s: float = 2.0,
    record: bool = True,
    quiet: bool = False,
) -> tuple[Path | None, dict]:
    """Runs a timed experiment without a window. With `phases`, prompts on the console for each
    head position and labels the data; their durations replace `duration_s`."""
    session.start()
    recorder = None
    try:
        time.sleep(warmup_s)
        recorder = start_recording(session, raw_video) if record else None
        plan = phases or [(None, duration_s)]
        for name, seconds in plan:
            if recorder and name:
                recorder.set_phase(name)
                print(f"\n>>> phase '{name}': hold for {seconds:g} s", flush=True)
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                time.sleep(min(1.0, max(0.0, end - time.monotonic())))
                if not quiet:
                    print(format_status_line(session), flush=True)
    finally:
        summary = stop_recording(session, recorder) if recorder else {}
        session.stop()
    return (recorder.run_dir if recorder else None), summary


def bench_modes(
    base: ExperimentConfig, modes: list[CaptureSettings], seconds: float, with_processing: bool
) -> list[dict]:
    """Runs all configured cameras simultaneously in each mode and reports what was achieved."""
    rows = []
    for mode in modes:
        config = ExperimentConfig(**{**base.__dict__})
        config.capture = CaptureSettings(
            mode.fourcc,
            mode.width,
            mode.height,
            mode.fps,
            base.capture.buffer_size,
            dict(base.capture.controls),
        )
        config.experiment_id = (
            f"{base.experiment_id}-bench-{mode.fourcc}-{mode.width}x{mode.height}-{mode.fps:g}"
        )
        processors = (
            base.processing
            if with_processing
            else {name: ProcessorConfig(enabled=False) for name in base.processing}
        )
        session = Session(config, processors=processors)
        run_dir, summary = run_headless(session, seconds, quiet=True)
        for cid, camera in session.cameras.items():
            cam = summary.get("cameras", {}).get(cid, {})
            rows.append(
                {
                    "mode": mode.mode,
                    "camera_id": cid,
                    "negotiated": camera.worker.source.negotiated,
                    "fps": cam.get("fps"),
                    "est_drop_pct": cam.get("est_drop_pct"),
                    "interval_p95_ms": cam.get("interval_ms", {}).get("p95"),
                    "error": camera.worker.error,
                    "run_dir": str(run_dir),
                }
            )
            print(
                f"{mode.mode:>24}  {cid:9}  negotiated {rows[-1]['negotiated']:>22}  "
                f"fps {cam.get('fps')}  "
                f"drop% {cam.get('est_drop_pct')}  dt95 {rows[-1]['interval_p95_ms']} ms"
                f"{'  ERROR ' + str(camera.worker.error) if camera.worker.error else ''}",
                flush=True,
            )
    return rows


# --- calibration -------------------------------------------------------------------------------


def run_calibration(
    session: Session,
    out_dir: Path,
    grid: tuple[int, int] = (3, 3),
    settle_s: float = 0.8,
    dwell_s: float = 1.5,
    screen: tuple[int, int] | None = None,
) -> dict:
    """Shows targets full-screen and collects, per camera and eye, the iris-in-eye feature
    (MediaPipe) and the dark-pupil offset for each. Experimental; see calibration/__init__.py
    for what the result does and does not mean."""
    name = "LYNX SIGHT calibration"
    cv2.namedWindow(name, cv2.WINDOW_NORMAL)
    cv2.setWindowProperty(name, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)
    cv2.imshow(name, np.zeros((10, 10, 3), np.uint8))
    cv2.waitKey(300)
    if screen is None:
        _, _, w, h = cv2.getWindowImageRect(name)
        screen = (w, h) if w > 100 and h > 100 else (1920, 1080)
    width, height = screen
    targets = calibration.grid_targets(grid[0], grid[1], width, height)
    session.start()
    samples: list[dict] = []
    seen_tokens: dict[tuple[str, str], int] = {}
    aborted = False

    def collect(index: int, target: tuple[int, int]) -> None:
        for cid in session.cameras:
            for name_, result in (
                ("landmarks", session.board.latest(cid, "landmarks")),
                ("eyes", session.board.latest(cid, "eyes")),
            ):
                if result is None or result.data is None:
                    continue
                if seen_tokens.get((cid, name_)) == result.frame.seq:
                    continue
                seen_tokens[(cid, name_)] = result.frame.seq
                if isinstance(result.data, Landmarks):
                    h, w = result.frame.image.shape[:2]
                    sample = features.from_landmarks(
                        result.frame.t_capture_ns, cid, result.data.points, (w, h),
                        result.data.head_pose_deg,
                    )  # fmt: skip
                    found = [(e.eye, e.iris, 1.0) for e in sample.tracked_eyes]
                    feature = features.IRIS_IN_EYE
                elif isinstance(result.data, Eyes):
                    found = [
                        (r.label, r.pupil_offset, r.pupil.confidence)
                        for r in result.data.regions
                        if r.pupil_offset and r.pupil and r.pupil.confidence >= 0.3
                    ]
                    feature = features.PUPIL_OFFSET
                else:
                    continue
                for eye, offset, confidence in found:
                    samples.append(
                        {
                            "target": index,
                            "screen": list(target),
                            "feature": feature,
                            "camera_id": cid,
                            "eye": eye,
                            "offset": [float(offset[0]), float(offset[1])],
                            "confidence": float(confidence),
                        }
                    )

    try:
        for index, (tx, ty) in enumerate(targets):
            start = time.monotonic()
            while time.monotonic() - start < settle_s + dwell_s:
                canvas = np.zeros((height, width, 3), np.uint8)
                collecting = time.monotonic() - start >= settle_s
                cv2.circle(canvas, (tx, ty), 18, (0, 0, 255) if not collecting else (0, 255, 0), 2)
                cv2.circle(canvas, (tx, ty), 3, (255, 255, 255), -1)
                cv2.putText(
                    canvas,
                    f"target {index + 1}/{len(targets)} - look at the dot, keep your head still"
                    " (Esc aborts)",
                    (30, 40),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.8,
                    (180, 180, 180),
                    2,
                )
                cv2.imshow(name, canvas)
                if (cv2.waitKey(10) & 0xFF) == 27:
                    aborted = True
                    break
                if collecting:
                    collect(index, (tx, ty))
            if aborted:
                break
    finally:
        session.stop()
        cv2.destroyWindow(name)

    out_dir.mkdir(parents=True, exist_ok=True)
    # Each camera, eye and feature set is fitted on its own: pooling them mixes sources with
    # different biases, which made the first hardware run (2026-11-01) unusable.
    fits = calibration.fit_sources(samples)
    best = calibration.best_source(fits)
    report: dict = {
        "experimental": True,
        "screen_px": [width, height],
        "grid": list(grid),
        "targets": len(targets),
        "aborted": aborted,
        "best_source": best,
        "fits": fits,
    }
    if best is None:
        report["error"] = "no camera/eye had 6 targets with enough samples"
    (out_dir / "calibration.json").write_text(json.dumps(report, indent=2))
    with (out_dir / "samples.jsonl").open("w") as fh:
        for s in samples:
            fh.write(json.dumps(s) + "\n")
    return report
