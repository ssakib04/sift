"""Candidate CV upload, native parsing, and persistence."""

import uuid
from pathlib import Path

import aiofiles
from fastapi import APIRouter, Depends, Form, Request, UploadFile, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.core.db import get_session
from app.models.candidate import Candidate
from app.models.cv import CV
from app.services.cv_parser import calculate_sha256, parse_cv_bytes

router = APIRouter()

MAX_CV_FILE_BYTES = 5 * 1024 * 1024
RAW_CV_DIRECTORY = Path("data/cvs/raw")
PDF_MEDIA_TYPE = "application/pdf"
DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_ALLOWED_MEDIA_TYPES = {
    ".pdf": PDF_MEDIA_TYPE,
    ".docx": DOCX_MEDIA_TYPE,
}


class ErrorResponse(BaseModel):
    """Standard API error body."""

    error_code: str
    message: str
    request_id: str


class CVUploadResponse(BaseModel):
    """Persisted CV and the candidate it belongs to."""

    cv_id: uuid.UUID
    candidate_id: uuid.UUID
    file_hash: str
    file_name: str
    file_size: int
    mime_type: str
    file_path: str
    character_count: int
    extraction_status: str


@router.post(
    "/upload",
    response_model=CVUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload a candidate CV",
    responses={
        status.HTTP_400_BAD_REQUEST: {"model": ErrorResponse},
        status.HTTP_409_CONFLICT: {"model": ErrorResponse},
    },
)
async def upload_cv(
    request: Request,
    file: UploadFile,
    full_name: str = Form(...),
    email: str = Form(...),
    session: Session = Depends(get_session),
) -> CVUploadResponse | JSONResponse:
    """Validate, parse, store, and persist a PDF or DOCX curriculum vitae."""
    request_id = _request_id(request)
    normalized_name = full_name.strip()
    normalized_email = email.strip()
    candidate_error = _candidate_error(normalized_name, normalized_email)
    if candidate_error is not None:
        return _error_response(
            status.HTTP_400_BAD_REQUEST,
            "INVALID_CANDIDATE",
            candidate_error,
            request_id,
        )

    safe_name = _safe_filename(file.filename)
    media_type = _media_type(file)
    extension = Path(safe_name).suffix.lower() if safe_name is not None else ""
    expected_media_type = _ALLOWED_MEDIA_TYPES.get(extension)
    if safe_name is None or expected_media_type is None or media_type != expected_media_type:
        return _error_response(
            status.HTTP_400_BAD_REQUEST,
            "UNSUPPORTED_CV_TYPE",
            "CV file must be a PDF or DOCX document.",
            request_id,
        )

    file_bytes = await file.read()
    if len(file_bytes) > MAX_CV_FILE_BYTES:
        return _error_response(
            status.HTTP_400_BAD_REQUEST,
            "CV_FILE_TOO_LARGE",
            "CV file exceeds the 5MB limit.",
            request_id,
        )

    file_hash = calculate_sha256(file_bytes)
    duplicate = session.exec(select(CV).where(CV.file_hash == file_hash)).first()
    if duplicate is not None:
        return _error_response(
            status.HTTP_409_CONFLICT,
            "DUPLICATE_CV",
            "A CV with this file hash has already been uploaded.",
            request_id,
        )

    try:
        parsed = parse_cv_bytes(file_bytes, safe_name)
    except ValueError as exc:
        return _error_response(
            status.HTTP_400_BAD_REQUEST,
            "CV_PARSE_FAILED",
            _parse_failure_message(exc),
            request_id,
        )

    raw_text = str(parsed["raw_text"])
    character_count = int(parsed["character_count"])
    extraction_status = str(parsed["extraction_status"])
    if not raw_text.strip():
        return _error_response(
            status.HTTP_400_BAD_REQUEST,
            "CV_PARSE_FAILED",
            "The uploaded CV could not be processed.",
            request_id,
        )

    destination = RAW_CV_DIRECTORY / f"{file_hash}_{safe_name}"
    relative_path = destination.as_posix()
    if len(relative_path) > 1024:
        return _error_response(
            status.HTTP_400_BAD_REQUEST,
            "UNSUPPORTED_CV_TYPE",
            "CV file name is too long.",
            request_id,
        )

    candidate = session.exec(select(Candidate).where(Candidate.email == normalized_email)).first()
    new_candidate = candidate is None
    if candidate is None:
        candidate = Candidate(full_name=normalized_name, email=normalized_email)

    try:
        cv = CV(
            candidate_id=candidate.id,
            file_hash=file_hash,
            file_name=safe_name,
            file_size=len(file_bytes),
            mime_type=media_type,
            file_path=relative_path,
            raw_text=raw_text,
            character_count=character_count,
            extraction_status=extraction_status,
        )
    except ValidationError:
        return _error_response(
            status.HTTP_400_BAD_REQUEST,
            "CV_PARSE_FAILED",
            "The uploaded CV could not be processed.",
            request_id,
        )

    try:
        await _write_raw_cv(destination, file_bytes)
    except OSError:
        return _error_response(
            status.HTTP_400_BAD_REQUEST,
            "CV_PARSE_FAILED",
            "The uploaded CV could not be processed.",
            request_id,
        )

    if new_candidate:
        session.add(candidate)
    session.add(cv)
    try:
        session.commit()
        session.refresh(cv)
    except IntegrityError:
        session.rollback()
        destination.unlink(missing_ok=True)
        return _error_response(
            status.HTTP_409_CONFLICT,
            "DUPLICATE_CV",
            "A CV with this file hash has already been uploaded.",
            request_id,
        )

    return CVUploadResponse(
        cv_id=cv.id,
        candidate_id=cv.candidate_id,
        file_hash=cv.file_hash,
        file_name=cv.file_name,
        file_size=cv.file_size,
        mime_type=cv.mime_type,
        file_path=cv.file_path,
        character_count=cv.character_count,
        extraction_status=cv.extraction_status,
    )


def _request_id(request: Request) -> str:
    supplied = request.headers.get("x-request-id", "").strip()
    if supplied:
        return supplied[:64]
    return f"req_{uuid.uuid4().hex[:12]}"


def _candidate_error(full_name: str, email: str) -> str | None:
    try:
        Candidate(full_name=full_name, email=email)
    except ValidationError as exc:
        errors = exc.errors()
        if not errors:
            return "Candidate details are invalid."
        location = ".".join(str(part) for part in errors[0]["loc"])
        return f"{location}: {errors[0]['msg']}"
    return None


def _safe_filename(filename: str | None) -> str | None:
    if filename is None:
        return None
    basename = Path(filename).name.strip()
    if basename in {"", ".", ".."}:
        return None
    return basename


def _media_type(upload: UploadFile) -> str:
    raw_type = upload.content_type or ""
    return raw_type.split(";", 1)[0].strip().lower()


def _parse_failure_message(exc: ValueError) -> str:
    detail = str(exc).removeprefix("CV_PARSE_FAILED:").strip()
    if detail:
        return f"The uploaded CV could not be processed. {detail}"
    return "The uploaded CV could not be processed."


def _error_response(
    status_code: int,
    error_code: str,
    message: str,
    request_id: str,
) -> JSONResponse:
    payload = ErrorResponse(error_code=error_code, message=message, request_id=request_id)
    return JSONResponse(status_code=status_code, content=payload.model_dump())


async def _write_raw_cv(destination: Path, file_bytes: bytes) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    async with aiofiles.open(destination, "wb") as raw_file:
        await raw_file.write(file_bytes)
