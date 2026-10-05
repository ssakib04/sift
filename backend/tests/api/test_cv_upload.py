"""Integration tests for CV ingestion through the upload API."""

import io
from collections.abc import AsyncIterator, Generator
from contextlib import asynccontextmanager
from pathlib import Path

import fitz
import pytest
from docx import Document
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, create_engine, select

from app.api.v1.cv import DOCX_MEDIA_TYPE, MAX_CV_FILE_BYTES, PDF_MEDIA_TYPE, RAW_CV_DIRECTORY
from app.core.db import get_session, init_db
from app.main import app
from app.models.candidate import Candidate
from app.models.cv import CV
from app.services.cv_parser import calculate_sha256

_COMPLETED_TEXT = (
    "Experienced Python engineer who built FastAPI services and production RAG pipelines."
)
_UPLOAD_PATH = "/api/v1/cv/upload"


@pytest.fixture
def anyio_backend() -> str:
    """Run async integration tests on asyncio."""
    return "asyncio"


@pytest.fixture
def db_engine() -> Generator[Engine, None, None]:
    """Provide a shared in-memory database for one upload scenario."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    init_db(engine)

    def override_session() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    try:
        yield engine
    finally:
        app.dependency_overrides.clear()


@asynccontextmanager
async def _api_client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def _pdf_bytes(text: str) -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_textbox(fitz.Rect(72, 72, 540, 720), text, fontsize=11)
    buffer = io.BytesIO()
    document.save(buffer)
    document.close()
    return buffer.getvalue()


def _docx_bytes(paragraphs: list[str]) -> bytes:
    document = Document()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _raw_file(payload: bytes, filename: str) -> Path:
    return RAW_CV_DIRECTORY / f"{calculate_sha256(payload)}_{filename}"


def _stored_cv(engine: Engine, email: str, file_hash: str) -> tuple[Candidate, CV]:
    with Session(engine) as session:
        candidate = session.exec(select(Candidate).where(Candidate.email == email)).one()
        cv = session.exec(select(CV).where(CV.file_hash == file_hash)).one()
        session.expunge(candidate)
        session.expunge(cv)
        return candidate, cv


@pytest.mark.anyio
async def test_upload_pdf_success(db_engine: Engine) -> None:
    """A valid PDF is stored on disk and persisted for the candidate."""
    payload = _pdf_bytes(_COMPLETED_TEXT)
    filename = "resume.pdf"
    email = "ada@example.com"
    stored = _raw_file(payload, filename)
    try:
        async with _api_client() as client:
            response = await client.post(
                _UPLOAD_PATH,
                data={"full_name": "Ada Lovelace", "email": email},
                files={"file": (filename, payload, PDF_MEDIA_TYPE)},
            )

        assert response.status_code in {200, 201}
        body = response.json()
        assert body["extraction_status"] == "completed"
        candidate, cv = _stored_cv(db_engine, email, calculate_sha256(payload))
        assert cv.candidate_id == candidate.id
        assert cv.extraction_status == "completed"
        assert stored.is_file()
        assert stored.parent == Path("data/cvs/raw")
    finally:
        stored.unlink(missing_ok=True)


@pytest.mark.anyio
async def test_upload_docx_success(db_engine: Engine) -> None:
    """A valid DOCX creates candidate and CV records."""
    payload = _docx_bytes([_COMPLETED_TEXT])
    filename = "resume.docx"
    email = "grace@example.com"
    stored = _raw_file(payload, filename)
    try:
        async with _api_client() as client:
            response = await client.post(
                _UPLOAD_PATH,
                data={"full_name": "Grace Hopper", "email": email},
                files={"file": (filename, payload, DOCX_MEDIA_TYPE)},
            )

        assert response.status_code in {200, 201}
        candidate, cv = _stored_cv(db_engine, email, calculate_sha256(payload))
        assert cv.candidate_id == candidate.id
        assert cv.file_name == filename
        assert stored.is_file()
    finally:
        stored.unlink(missing_ok=True)


@pytest.mark.anyio
async def test_upload_duplicate_hash_rejection(db_engine: Engine) -> None:
    """Uploading the same bytes twice is rejected as a duplicate."""
    payload = _pdf_bytes(_COMPLETED_TEXT)
    filename = "duplicate.pdf"
    email = "ada@example.com"
    stored = _raw_file(payload, filename)
    form = {"full_name": "Ada Lovelace", "email": email}
    upload = {"file": (filename, payload, PDF_MEDIA_TYPE)}
    try:
        async with _api_client() as client:
            first = await client.post(_UPLOAD_PATH, data=form, files=upload)
            second = await client.post(_UPLOAD_PATH, data=form, files=upload)

        assert first.status_code in {200, 201}
        assert second.status_code in {400, 409}
        message = second.json()["message"].lower()
        assert "already" in message or "duplicate" in message
        with Session(db_engine) as session:
            matches = session.exec(select(CV).where(CV.file_hash == calculate_sha256(payload))).all()
            assert len(matches) == 1
    finally:
        stored.unlink(missing_ok=True)


@pytest.mark.anyio
async def test_upload_invalid_extension(db_engine: Engine) -> None:
    """Unsupported extensions are rejected before persistence."""
    async with _api_client() as client:
        response = await client.post(
            _UPLOAD_PATH,
            data={"full_name": "Ada Lovelace", "email": "ada@example.com"},
            files={"file": ("notes.txt", b"not a cv", "text/plain")},
        )

    assert response.status_code == 400
    body = response.json()
    assert body["message"]
    assert "pdf" in body["message"].lower() or "docx" in body["message"].lower()
    with Session(db_engine) as session:
        assert session.exec(select(CV)).all() == []


@pytest.mark.anyio
async def test_upload_oversized_file(db_engine: Engine) -> None:
    """Files larger than 5MB are rejected."""
    async with _api_client() as client:
        response = await client.post(
            _UPLOAD_PATH,
            data={"full_name": "Ada Lovelace", "email": "ada@example.com"},
            files={
                "file": (
                    "large.pdf",
                    b"x" * (MAX_CV_FILE_BYTES + 1),
                    PDF_MEDIA_TYPE,
                )
            },
        )

    assert response.status_code == 400
    message = response.json()["message"].lower()
    assert "5mb" in message or "size" in message or "limit" in message
    with Session(db_engine) as session:
        assert session.exec(select(CV)).all() == []


@pytest.mark.anyio
async def test_upload_low_density_pdf(db_engine: Engine) -> None:
    """A PDF with fewer than 50 characters is flagged for OCR."""
    payload = _pdf_bytes("Hi")
    filename = "scan.pdf"
    email = "candidate007@example.com"
    stored = _raw_file(payload, filename)
    try:
        async with _api_client() as client:
            response = await client.post(
                _UPLOAD_PATH,
                data={"full_name": "Candidate 007", "email": email},
                files={"file": (filename, payload, PDF_MEDIA_TYPE)},
            )

        assert response.status_code in {200, 201}
        assert response.json()["extraction_status"] == "low_density"
        _candidate, cv = _stored_cv(db_engine, email, calculate_sha256(payload))
        assert cv.extraction_status == "low_density"
        assert cv.character_count < 50
    finally:
        stored.unlink(missing_ok=True)
