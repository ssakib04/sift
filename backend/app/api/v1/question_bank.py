from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.schemas.question_bank import QuestionBankDocumentRead
from app.services.documents import EmptyDocumentError, UnsupportedDocumentError
from app.services.question_bank import ingest_question_bank, list_question_documents

router = APIRouter(prefix="/question-bank")
_MAX_BYTES = 10 * 1024 * 1024


@router.get("", response_model=list[QuestionBankDocumentRead])
async def read_question_bank(session: AsyncSession = Depends(get_session)) -> list[QuestionBankDocumentRead]:
    documents = await list_question_documents(session)
    return [
        QuestionBankDocumentRead(
            id=document.id,
            filename=document.filename,
            media_type=document.media_type,
            created_at=document.created_at,
            question_count=len(document.questions),
        )
        for document in documents
    ]


@router.post("", response_model=QuestionBankDocumentRead, status_code=201)
async def upload_question_bank(
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
) -> QuestionBankDocumentRead:
    filename = Path(file.filename or "questions").name
    data = await file.read()
    if len(data) > _MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail={"error_code": "QUESTION_BANK_TOO_LARGE", "message": "Question bank files must be 10 MB or smaller."},
        )
    try:
        document = await ingest_question_bank(
            session,
            filename=filename,
            media_type=file.content_type or "application/octet-stream",
            data=data,
        )
    except UnsupportedDocumentError as exc:
        raise HTTPException(
            status_code=415,
            detail={"error_code": "QUESTION_BANK_TYPE_UNSUPPORTED", "message": "Upload a PDF or DOCX question bank."},
        ) from exc
    except EmptyDocumentError as exc:
        raise HTTPException(
            status_code=422,
            detail={"error_code": "QUESTION_BANK_EMPTY", "message": str(exc)},
        ) from exc
    return QuestionBankDocumentRead(
        id=document.id,
        filename=document.filename,
        media_type=document.media_type,
        created_at=document.created_at,
        question_count=len(document.questions),
    )
