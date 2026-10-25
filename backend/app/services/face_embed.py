"""Turn a face photo into a 512-number vector.

Production uses InsightFace buffalo_l (SCRFD detection and ArcFace embeddings).
The hashing backend is the deterministic stand-in used when that model is not selected.
"""

import ctypes
import gc
import math
import sys
import threading
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any, Protocol

from app.core.config import Settings, get_settings
from app.models.candidate import FACE_DIMENSIONS

_insight: dict[tuple[str, str], "InsightFaceEmbedder"] = {}


@dataclass(frozen=True)
class FaceSample:
    embedding: list[float]
    confidence: float
    crop_jpeg: bytes
    portrait_jpeg: bytes = b""


class FaceEmbedder(Protocol):
    def embed(self, image: bytes) -> FaceSample | None:
        """Return the clearest face in the image, or None when no usable face is present."""


class HashingFaceEmbedder:
    """Pixel hash used when InsightFace is not selected. The same photo always yields the same vector."""

    def embed(self, image: bytes) -> FaceSample | None:
        from PIL import Image

        try:
            with Image.open(BytesIO(image)) as source:
                rgb = source.convert("RGB")
        except Exception:
            return None
        width, height = rgb.size
        if width < 48 or height < 48:
            return None
        small = rgb.resize((32, 32))
        pixels: list[tuple[int, int, int]] = []
        for y in range(small.height):
            for x in range(small.width):
                pixel = small.getpixel((x, y))
                channels = pixel if isinstance(pixel, tuple) else (pixel, pixel, pixel)
                pixels.append((int(channels[0]), int(channels[1]), int(channels[2])))
        luminance = [(red + green + blue) / 3 for red, green, blue in pixels]
        mean = sum(luminance) / len(luminance)
        variance = sum((value - mean) ** 2 for value in luminance) / len(luminance)
        if variance < 64:
            return None
        buckets = [0.0] * FACE_DIMENSIONS
        for index, (red, green, blue) in enumerate(pixels):
            buckets[(index * 3) % FACE_DIMENSIONS] += red / 255
            buckets[(index * 3 + 1) % FACE_DIMENSIONS] += green / 255
            buckets[(index * 3 + 2) % FACE_DIMENSIONS] += blue / 255
        encoded = BytesIO()
        rgb.save(encoded, format="JPEG", quality=85)
        spread = variance**0.5
        return FaceSample(embedding=_normalize(buckets), confidence=min(1.0, spread / 64), crop_jpeg=encoded.getvalue())


class InsightFaceEmbedder:
    """Local ArcFace embeddings from the buffalo_l pack. The model loads on the first face."""

    def __init__(self, model_name: str, root: str) -> None:
        self._model_name = model_name
        self._root = root
        self._app: Any = None
        self._lock = threading.Lock()

    def embed(self, image: bytes) -> FaceSample | None:
        with self._lock:
            return self._embed(image)

    def _embed(self, image: bytes) -> FaceSample | None:
        import cv2
        import numpy as np

        array = np.frombuffer(image, dtype=np.uint8)
        decoded = cv2.imdecode(array, cv2.IMREAD_COLOR)
        if decoded is None:
            return None
        faces = self._analysis().get(decoded)
        if not faces:
            return None
        face = max(faces, key=_face_area)
        crop = _crop_jpeg(decoded, face.bbox)
        if crop is None:
            return None
        vector = [float(item) for item in face.normed_embedding]
        if len(vector) != FACE_DIMENSIONS:
            raise RuntimeError("Face model returned an unexpected vector size.")
        return FaceSample(
            embedding=_normalize(vector),
            confidence=float(getattr(face, "det_score", 0.0)),
            crop_jpeg=crop,
        )

    def _analysis(self) -> Any:
        if self._app is None:
            from insightface.app import FaceAnalysis

            Path(self._root).mkdir(parents=True, exist_ok=True)
            try:
                app = FaceAnalysis(
                    name=self._model_name,
                    root=self._root,
                    providers=["CPUExecutionProvider"],
                )
            except TypeError:
                app = FaceAnalysis(name=self._model_name, root=self._root)
            app.prepare(ctx_id=-1, det_size=(640, 640))
            self._app = app
        return self._app

    def release(self) -> None:
        """Drop the ONNX sessions so the interview models can use the memory."""
        with self._lock:
            app = self._app
            self._app = None
        if app is None:
            return
        models = getattr(app, "models", None)
        if isinstance(models, dict):
            for name in list(models):
                model = models.pop(name)
                session = getattr(model, "session", None)
                if session is not None:
                    del session
                del model


def create_face_embedder(settings: Settings | None = None) -> FaceEmbedder:
    resolved = settings or get_settings()
    if resolved.face_backend == "hashing":
        return HashingFaceEmbedder()
    root = resolved.face_model_dir or str(Path(resolved.cv_storage_dir) / "insightface")
    key = (resolved.face_model, root)
    cached = _insight.get(key)
    if cached is None:
        cached = InsightFaceEmbedder(resolved.face_model, root)
        _insight[key] = cached
    return cached


def release_face_embedder() -> None:
    """Unload every cached face model and hand the memory back to the machine."""
    cached = list(_insight.values())
    _insight.clear()
    for embedder in cached:
        embedder.release()
    gc.collect()
    if sys.platform != "linux":
        return
    try:
        ctypes.CDLL("libc.so.6").malloc_trim(0)
    except OSError:
        return


def _normalize(values: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in values))
    if norm == 0:
        return values
    return [value / norm for value in values]


def _face_area(face: Any) -> float:
    box = face.bbox
    return max(0.0, float(box[2]) - float(box[0])) * max(0.0, float(box[3]) - float(box[1]))


def _crop_jpeg(image: Any, bbox: Any) -> bytes | None:
    import cv2

    height, width = image.shape[:2]
    x1 = max(0, int(bbox[0]))
    y1 = max(0, int(bbox[1]))
    x2 = min(width, int(bbox[2]))
    y2 = min(height, int(bbox[3]))
    if x2 <= x1 or y2 <= y1:
        return None
    ok, encoded = cv2.imencode(".jpg", image[y1:y2, x1:x2])
    if not ok:
        return None
    return encoded.tobytes()
