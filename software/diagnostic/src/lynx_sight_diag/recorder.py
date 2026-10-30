"""Experiment recording: per-frame timing, per-result measurements, events and a summary.

A run directory `<output_dir>/<experiment_id>/<YYYYmmdd-HHMMSS>/` holds

    config.yaml        the experiment config plus what the devices actually negotiated
    frames.jsonl       one line per captured frame (timing, estimated drops, phase)
    results.jsonl      one line per processing result (latency, confidence, positions)
    events.jsonl       start/stop, phase changes, control changes, errors, reconnects
    summary.json       aggregates computed from the files above (`summarize_run`)
    <cam>.avi + <cam>.timestamps.csv   optional raw video (MJPG) for replay

Writing happens on a background thread fed by bounded queues, so disk stalls never reach
capture; anything that could not be queued is counted in the summary as `record_dropped`.
"""

from __future__ import annotations

import csv
import dataclasses
import json
import math
import platform
import queue
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import yaml

from . import __version__
from .capture import FrameTiming
from .config import ExperimentConfig
from .frames import Frame
from .processing import Result
from .stats import Summary


def to_jsonable(value: Any, digits: int = 3) -> Any:
    """Dataclasses/numpy/tuples -> JSON types; large arrays become their shape only."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            f.name: to_jsonable(getattr(value, f.name), digits) for f in dataclasses.fields(value)
        }
    if isinstance(value, np.ndarray):
        if value.size > 64:
            return {"shape": list(value.shape)}
        return to_jsonable(value.tolist(), digits)
    if isinstance(value, dict):
        return {str(k): to_jsonable(v, digits) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(v, digits) for v in value]
    if isinstance(value, (np.floating, float)):
        return None if math.isnan(value) else round(float(value), digits)
    if isinstance(value, np.integer):
        return int(value)
    return value


def result_record(result: Result, phase: str | None) -> dict:
    return {
        "camera_id": result.camera_id,
        "processor": result.processor,
        "seq": result.frame.seq,
        "t_capture_ns": result.frame.t_capture_ns,
        "latency_ms": round(result.latency_ms, 3),
        "compute_ms": round(result.compute_ms, 3),
        "phase": phase,
        "error": result.error,
        "data": to_jsonable(result.data),
    }


class Recorder:
    def __init__(self, config: ExperimentConfig, raw_video: bool = False, root: Path | None = None):
        stamp = time.strftime("%Y%m%d-%H%M%S")
        self.config = config
        self.run_dir = Path(root or config.output_dir) / config.experiment_id / stamp
        self.run_dir.mkdir(parents=True, exist_ok=False)
        self.raw_video = raw_video
        self.phase: str | None = None
        self.dropped = 0
        self._records: queue.Queue = queue.Queue(maxsize=20_000)
        self._frames: queue.Queue = queue.Queue(maxsize=64)
        self._writers: dict[str, tuple[cv2.VideoWriter, Any, Any]] = {}
        self._stop = threading.Event()
        self._files = {
            name: (self.run_dir / f"{name}.jsonl").open("a", buffering=1)
            for name in ("frames", "results", "events")
        }
        self._thread = threading.Thread(target=self._drain, name="recorder", daemon=True)
        self._thread.start()

    # -- inputs (called from capture/processing threads) ----------------------------------------

    def _put(self, q: queue.Queue, item) -> None:
        try:
            q.put_nowait(item)
        except queue.Full:
            self.dropped += 1

    def on_frame(self, frame: Frame, timing: FrameTiming) -> None:
        record = dataclasses.asdict(timing)
        record["phase"] = self.phase
        record["interval_ms"] = None if timing.interval_ms is None else round(timing.interval_ms, 3)
        record["read_ms"] = round(timing.read_ms, 3)
        self._put(self._records, ("frames", record))
        if self.raw_video:
            self._put(self._frames, frame)

    def on_result(self, result: Result) -> None:
        self._put(self._records, ("results", result_record(result, self.phase)))

    def event(self, kind: str, **fields) -> None:
        self._put(self._records, ("events", {"t_ns": time.monotonic_ns(), "event": kind, **fields}))

    def set_phase(self, phase: str | None) -> None:
        self.phase = phase
        self.event("phase", phase=phase)

    # -- output ---------------------------------------------------------------------------------

    def write_config(self, extra: dict) -> None:
        data = self.config.to_dict()
        data["run"] = {
            "software": f"lynx-sight-diagnostic {__version__}",
            "opencv": cv2.__version__,
            "python": platform.python_version(),
            "host": platform.node(),
            "kernel": platform.release(),
            "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            **extra,
        }
        (self.run_dir / "config.yaml").write_text(
            yaml.safe_dump(to_jsonable(data), sort_keys=False)
        )

    def _video(self, frame: Frame):
        entry = self._writers.get(frame.camera_id)
        if entry is None:
            path = self.run_dir / f"{frame.camera_id}.avi"
            writer = cv2.VideoWriter(
                str(path),
                cv2.VideoWriter_fourcc(*"MJPG"),
                float(self.config.capture.fps),
                (frame.width, frame.height),
                False,
            )
            fh = path.with_suffix(".timestamps.csv").open("w", newline="")
            out = csv.writer(fh)
            out.writerow(["seq", "t_capture_ns", "t_device_ms"])
            entry = self._writers[frame.camera_id] = (writer, fh, out)
        return entry

    def _drain(self) -> None:
        while not (self._stop.is_set() and self._records.empty() and self._frames.empty()):
            busy = False
            try:
                name, record = self._records.get(timeout=0.05)
                self._files[name].write(json.dumps(record) + "\n")
                busy = True
            except queue.Empty:
                pass
            try:
                frame = self._frames.get_nowait()
                writer, _fh, out = self._video(frame)
                writer.write(frame.image)
                out.writerow([frame.seq, frame.t_capture_ns, frame.t_device_ms])
                busy = True
            except queue.Empty:
                pass
            if not busy and self._stop.is_set():
                break

    def close(self) -> dict:
        self.event("stop")
        self._stop.set()
        self._thread.join(30)
        for fh in self._files.values():
            fh.close()
        for writer, fh, _ in self._writers.values():
            writer.release()
            fh.close()
        summary = summarize_run(self.run_dir)
        summary["record_dropped"] = self.dropped
        (self.run_dir / "summary.json").write_text(json.dumps(summary, indent=2))
        return summary


# --- summary -----------------------------------------------------------------------------------


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open() as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _mean(values: list[float]) -> float | None:
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 4) if values else None


def summarize_records(frames: list[dict], results: list[dict]) -> dict:
    """Aggregates recorded frames and results; pure, so it is unit-tested directly."""
    out: dict[str, Any] = {"cameras": {}, "processors": {}, "phases": {}}
    by_cam: dict[str, list[dict]] = defaultdict(list)
    for f in frames:
        by_cam[f["camera_id"]].append(f)
    for cid, items in sorted(by_cam.items()):
        stamps = [f["t_capture_ns"] for f in items]
        span_s = (max(stamps) - min(stamps)) / 1e9 if len(stamps) > 1 else 0.0
        dropped = sum(f.get("est_dropped", 0) for f in items)
        out["cameras"][cid] = {
            "frames": len(items),
            "duration_s": round(span_s, 3),
            "fps": round((len(items) - 1) / span_s, 3) if span_s > 0 else None,
            "est_dropped": dropped,
            "est_drop_pct": round(100 * dropped / (len(items) + dropped), 3) if items else None,
            "interval_ms": Summary.of(
                f["interval_ms"] for f in items if f["interval_ms"] is not None
            ).as_dict(),
            "read_ms": Summary.of(f["read_ms"] for f in items).as_dict(),
        }

    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for r in results:
        groups[(r["camera_id"], r["processor"])].append(r)
    for (cid, proc), items in sorted(groups.items()):
        ok = [r for r in items if not r["error"]]
        entry = {
            "results": len(items),
            "errors": len(items) - len(ok),
            "latency_ms": Summary.of(r["latency_ms"] for r in ok).as_dict(),
            "compute_ms": Summary.of(r["compute_ms"] for r in ok).as_dict(),
        }
        entry.update(_detection_stats(proc, ok))
        out["processors"][f"{cid}/{proc}"] = entry

    phases: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        if r.get("phase") and not r["error"] and r["processor"] in ("face", "eyes"):
            phases[r["phase"]].append(r)
    for phase, items in phases.items():
        per = {}
        for cid in sorted({r["camera_id"] for r in items}):
            per[cid] = {}
            for proc in ("face", "eyes"):
                subset = [r for r in items if r["camera_id"] == cid and r["processor"] == proc]
                if subset:
                    per[cid].update(_detection_stats(proc, subset))
        out["phases"][phase] = per
    return out


def _detection_stats(processor: str, ok: list[dict]) -> dict:
    if not ok:
        return {}
    if processor == "face":
        found = [r for r in ok if r["data"] and r["data"]["faces"]]
        return {
            "face_detect_rate": round(len(found) / len(ok), 4),
            "face_score_mean": _mean([r["data"]["faces"][0]["score"] for r in found]),
        }
    if processor == "eyes":
        present = [r["data"] for r in ok if r["data"]]
        regions = [reg for d in present for reg in d["regions"]]
        pupils = [reg for reg in regions if reg["pupil"]]
        return {
            "eyes_frames": len(present),
            "eye_regions": len(regions),
            "pupil_found_rate": round(len(pupils) / len(regions), 4) if regions else None,
            "pupil_confidence_mean": _mean([p["pupil"]["confidence"] for p in pupils]),
            "eye_distance_px_mean": _mean([d["eye_distance_px"] for d in present]),
            "roll_deg_mean": _mean([d["roll_deg"] for d in present]),
            "face_centre_x_mean": _mean([d["face_centre_norm"][0] for d in present]),
            "face_centre_y_mean": _mean([d["face_centre_norm"][1] for d in present]),
        }
    if processor == "quality":
        return {
            "mean_level": _mean([r["data"]["mean"] for r in ok]),
            "saturated_pct_mean": _mean([r["data"]["saturated_pct"] for r in ok]),
            "sharpness_mean": _mean([r["data"]["sharpness"] for r in ok]),
        }
    return {}


def summarize_run(run_dir: str | Path) -> dict:
    run_dir = Path(run_dir)
    return summarize_records(
        _read_jsonl(run_dir / "frames.jsonl"), _read_jsonl(run_dir / "results.jsonl")
    )
