"""A diagnostic session: cameras, their capture workers and processing runners, wired together.

    camera source -> CaptureWorker -> FrameSlot ---> quality runner ----\
                                                |-> face runner ---------> ResultBoard -> UI
                                                |       `-> eyes runner -/            `-> recorder
                                                `-> landmarks runner ---/

Each arrow into a runner is non-blocking ("newest input wins"); see processing/__init__.py.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .capture import CaptureStatus, CaptureWorker
from .config import ExperimentConfig, ProcessorConfig
from .frames import FrameSlot
from .processing import Processor, ProcessorRunner, ResultBoard
from .processing.eyes import EyesProcessor
from .processing.face import FaceProcessor
from .processing.landmarks import LandmarksProcessor
from .processing.quality import QualityProcessor
from .sources import FrameSource, make_source

PROCESSORS: dict[str, Callable[..., Processor]] = {
    "quality": QualityProcessor,
    "face": FaceProcessor,
    "eyes": EyesProcessor,
    "landmarks": LandmarksProcessor,
}


@dataclass
class CameraPipeline:
    camera_id: str
    worker: CaptureWorker
    runners: list[ProcessorRunner]

    @property
    def slot(self) -> FrameSlot:
        return self.worker.slot


class Session:
    def __init__(
        self,
        config: ExperimentConfig,
        sources: dict[str, FrameSource] | None = None,
        processors: dict[str, ProcessorConfig] | None = None,
    ):
        self.config = config
        self.board = ResultBoard()
        self.cameras: dict[str, CameraPipeline] = {}
        enabled = {
            name: cfg for name, cfg in (processors or config.processing).items() if cfg.enabled
        }
        # A downstream processor without its upstream would never run.
        if "eyes" in enabled and "face" not in enabled:
            del enabled["eyes"]
        for camera_id, camera in config.cameras.items():
            source = (sources or {}).get(camera_id) or make_source(
                camera_id, camera.device, config.capture_for(camera_id)
            )
            worker = CaptureWorker(camera_id, source)
            runners = [
                ProcessorRunner(
                    PROCESSORS[name](**cfg.options), camera_id, worker.slot, self.board, cfg.max_hz
                )
                for name, cfg in enabled.items()
            ]
            self.cameras[camera_id] = CameraPipeline(camera_id, worker, runners)

    def start(self) -> None:
        for camera in self.cameras.values():
            for runner in camera.runners:
                runner.start()
            camera.worker.start()

    def stop(self) -> None:
        for camera in self.cameras.values():
            camera.worker.stop()
            for runner in camera.runners:
                runner.stop()
                close = getattr(runner.processor, "close", None)
                if close:
                    close()

    def pause(self) -> None:
        for camera in self.cameras.values():
            camera.worker.stop()

    def resume(self) -> None:
        for camera in self.cameras.values():
            camera.worker.start()

    def reconnect(self, camera_id: str | None = None) -> None:
        for cid, camera in self.cameras.items():
            if camera_id in (None, cid):
                camera.worker.restart()

    def set_processor_enabled(self, name: str, enabled: bool) -> None:
        for camera in self.cameras.values():
            for runner in camera.runners:
                if runner.name == name:
                    runner.enabled = enabled

    def adjust_control(
        self, camera_id: str, key: str, delta: int | None = None, value: int | None = None
    ):
        """Changes a control on a running camera; returns (new value, error text)."""
        controls = self.cameras[camera_id].worker.source.controls
        if controls is None:
            return None, "no controls (camera not open?)"
        info = controls.available().get(key)
        if info is None:
            return None, f"{key} not supported"
        try:
            current = controls.get(key)
            target = (
                value
                if value is not None
                else (current if current is not None else info.default) + (delta or 0)
            )
            return controls.set(key, target), None
        except (OSError, KeyError) as exc:
            return None, str(exc)

    def status(self) -> dict[str, CaptureStatus]:
        return {cid: camera.worker.status() for cid, camera in self.cameras.items()}
