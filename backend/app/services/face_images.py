"""Pull candidate photos out of CV files and keep that photo beside the record."""

import zipfile
from dataclasses import replace
from io import BytesIO
from pathlib import Path
from uuid import UUID

from app.services.face_embed import FaceEmbedder, FaceSample

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
_MIN_SIDE = 48


def extract_document_images(filename: str, data: bytes) -> list[bytes]:
    """Return embedded photos large enough to be a headshot."""
    suffix = Path(filename).suffix.lower()
    if suffix == ".pdf":
        raw_images = _pdf_images(data)
    elif suffix == ".docx":
        raw_images = _docx_images(data)
    else:
        return []
    kept: list[bytes] = []
    seen: set[bytes] = set()
    for image in raw_images:
        if image in seen or not _large_enough(image):
            continue
        seen.add(image)
        kept.append(image)
    return kept


def enroll_from_document(filename: str, data: bytes, embedder: FaceEmbedder) -> FaceSample | None:
    """Embed the clearest face found in the CV. The stored portrait is that CV photo, not a face cut."""
    best: FaceSample | None = None
    best_source: bytes | None = None
    for image in extract_document_images(filename, data):
        sample = embedder.embed(image)
        if sample is None:
            continue
        if best is None or sample.confidence > best.confidence:
            best = sample
            best_source = image
    if best is None or best_source is None:
        return None
    portrait = encode_portrait(best_source)
    if portrait is None:
        return best
    return replace(best, portrait_jpeg=portrait)


def encode_portrait(image: bytes) -> bytes | None:
    """JPEG of the CV photo at its original size."""
    from PIL import Image

    try:
        with Image.open(BytesIO(image)) as source:
            rgb = source.convert("RGB")
            encoded = BytesIO()
            rgb.save(encoded, format="JPEG", quality=92)
    except Exception:
        return None
    return encoded.getvalue()


def candidate_photo_file(storage_dir: str, candidate_id: UUID, stored: str) -> Path | None:
    """Return the enrolled portrait only when it is the face file for this candidate."""
    root = (Path(storage_dir) / "faces").resolve()
    path = Path(stored)
    if not path.is_absolute():
        path = root / path
    resolved = path.resolve()
    if resolved.parent != root or resolved.name != f"{candidate_id}.jpg" or not resolved.is_file():
        return None
    return resolved


def write_face_crop(storage_dir: str, candidate_id: UUID, jpeg: bytes) -> str:
    folder = Path(storage_dir) / "faces"
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / f"{candidate_id}.jpg"
    destination.write_bytes(jpeg)
    return str(destination)


def _pdf_images(data: bytes) -> list[bytes]:
    import fitz

    images: list[bytes] = []
    try:
        document = fitz.open(stream=data, filetype="pdf")
    except Exception:
        return []
    try:
        for page in document:
            for item in page.get_images(full=True):
                extracted = document.extract_image(item[0])
                blob = extracted.get("image") if extracted else None
                if isinstance(blob, bytes) and blob:
                    images.append(blob)
    finally:
        document.close()
    return images


def _docx_images(data: bytes) -> list[bytes]:
    images: list[bytes] = []
    try:
        archive = zipfile.ZipFile(BytesIO(data))
    except zipfile.BadZipFile:
        return []
    with archive:
        for name in archive.namelist():
            if not name.startswith("word/media/"):
                continue
            if Path(name).suffix.lower() not in _IMAGE_SUFFIXES:
                continue
            images.append(archive.read(name))
    return images


def _large_enough(image: bytes) -> bool:
    from PIL import Image

    try:
        with Image.open(BytesIO(image)) as source:
            width, height = source.size
    except Exception:
        return False
    return width >= _MIN_SIDE and height >= _MIN_SIDE
