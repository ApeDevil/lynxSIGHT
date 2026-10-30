"""Pretrained models: where they live, where they come from, and integrity checks.

The YuNet face detector (MIT, 233 kB) ships in the repository so face detection works after a
plain clone. The larger optional MediaPipe Face Landmarker model is downloaded on request with
`sight-diag models fetch` into the user cache.
"""

from __future__ import annotations

import hashlib
import os
import urllib.request
from dataclasses import dataclass
from pathlib import Path

REPO_MODELS = Path(__file__).resolve().parents[2] / "models"
CACHE_MODELS = (
    Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "lynx-sight" / "models"
)


@dataclass(frozen=True)
class Model:
    key: str
    filename: str
    url: str
    sha256: str
    licence: str


MODELS = {
    "yunet": Model(
        "yunet",
        "face_detection_yunet_2023mar.onnx",
        "https://media.githubusercontent.com/media/opencv/opencv_zoo/main/models/"
        "face_detection_yunet/face_detection_yunet_2023mar.onnx",
        "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
        "MIT (OpenCV Zoo, Shiqi Yu)",
    ),
    "face_landmarker": Model(
        "face_landmarker",
        "face_landmarker.task",
        "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/"
        "face_landmarker.task",
        "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff",
        "Apache-2.0 (Google MediaPipe)",
    ),
}


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def locate(key: str) -> Path | None:
    """Path of a model with a matching checksum in $LYNX_SIGHT_MODELS, the repo or the cache."""
    model = MODELS[key]
    dirs = [Path(p) for p in os.environ.get("LYNX_SIGHT_MODELS", "").split(os.pathsep) if p]
    for directory in (*dirs, REPO_MODELS, CACHE_MODELS):
        path = directory / model.filename
        if path.is_file() and sha256_of(path) == model.sha256:
            return path
    return None


def fetch(key: str, directory: Path = CACHE_MODELS) -> Path:
    """Downloads a model and verifies its checksum."""
    model = MODELS[key]
    existing = locate(key)
    if existing:
        return existing
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / model.filename
    tmp = target.with_suffix(".part")
    with urllib.request.urlopen(model.url, timeout=60) as response, tmp.open("wb") as fh:
        while chunk := response.read(1 << 20):
            fh.write(chunk)
    actual = sha256_of(tmp)
    if actual != model.sha256:
        tmp.unlink()
        raise RuntimeError(f"{model.filename}: checksum mismatch ({actual})")
    tmp.replace(target)
    return target
