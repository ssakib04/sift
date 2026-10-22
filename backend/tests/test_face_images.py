import zipfile
from io import BytesIO
from uuid import uuid4

from PIL import Image

from app.services.face_embed import FaceSample, HashingFaceEmbedder
from app.services.face_images import candidate_photo_file, enroll_from_document, extract_document_images, write_face_crop


def varied_png(width: int, height: int, *, seed: int = 3) -> bytes:
    image = Image.new("RGB", (width, height))
    pixels = [
        ((x * seed) % 256, (y * (seed + 2)) % 256, (x + y * seed) % 256)
        for y in range(height)
        for x in range(width)
    ]
    image.putdata(pixels)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def flat_png(width: int, height: int) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (width, height), (40, 40, 40)).save(buffer, format="PNG")
    return buffer.getvalue()


def _pdf(*images: bytes) -> bytes:
    import fitz

    document = fitz.open()
    page = document.new_page()
    top = 36
    for image in images:
        page.insert_image(fitz.Rect(36, top, 180, top + 140), stream=image)
        top += 160
    data = document.tobytes()
    document.close()
    return data


def test_pdf_keeps_a_headshot_and_drops_a_tiny_logo() -> None:
    data = _pdf(varied_png(96, 120), varied_png(12, 12))
    images = extract_document_images("ada.pdf", data)
    assert len(images) == 1
    with Image.open(BytesIO(images[0])) as photo:
        assert photo.size[0] >= 48 and photo.size[1] >= 48


def test_docx_reads_media_images_and_ignores_other_parts() -> None:
    photo = varied_png(64, 64)
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/media/portrait.png", photo)
        archive.writestr("word/media/notes.txt", b"not an image")
        archive.writestr("[Content_Types].xml", b"<Types/>")
    images = extract_document_images("ada.docx", buffer.getvalue())
    assert images == [photo]


def test_unsupported_and_broken_files_enroll_nothing() -> None:
    assert extract_document_images("notes.txt", b"hello") == []
    assert extract_document_images("broken.pdf", b"not a pdf") == []
    assert extract_document_images("broken.docx", b"not a zip") == []


def test_enrollment_uses_the_clearest_face_and_writes_the_crop(tmp_path) -> None:
    data = _pdf(varied_png(72, 72, seed=3), varied_png(72, 72, seed=11))
    sample = enroll_from_document("ada.pdf", data, HashingFaceEmbedder())
    assert sample is not None
    candidate_id = uuid4()
    path = write_face_crop(str(tmp_path), candidate_id, sample.crop_jpeg)
    assert path.endswith(f"{candidate_id}.jpg")
    assert (tmp_path / "faces" / f"{candidate_id}.jpg").read_bytes() == sample.crop_jpeg


def test_portrait_lookup_stays_inside_the_faces_folder(tmp_path) -> None:
    candidate_id = uuid4()
    stored = write_face_crop(str(tmp_path), candidate_id, b"jpeg-bytes")
    assert candidate_photo_file(str(tmp_path), candidate_id, stored) == (tmp_path / "faces" / f"{candidate_id}.jpg").resolve()
    outside = tmp_path / "secret.jpg"
    outside.write_bytes(b"nope")
    assert candidate_photo_file(str(tmp_path), candidate_id, str(outside)) is None
    assert candidate_photo_file(str(tmp_path), uuid4(), stored) is None


def test_enrollment_keeps_the_cv_photo_instead_of_the_face_cut() -> None:
    class TightCrop:
        def embed(self, image: bytes) -> FaceSample:
            return FaceSample(embedding=[1.0], confidence=0.9, crop_jpeg=b"\xff\xd8tiny")

    source = varied_png(96, 120)
    sample = enroll_from_document("ada.pdf", _pdf(source), TightCrop())
    assert sample is not None
    assert sample.crop_jpeg == b"\xff\xd8tiny"
    with Image.open(BytesIO(sample.portrait_jpeg)) as photo:
        assert photo.size == (96, 120)


def test_a_document_of_only_flat_images_does_not_enroll() -> None:
    data = _pdf(flat_png(80, 80))
    assert enroll_from_document("ada.pdf", data, HashingFaceEmbedder()) is None
