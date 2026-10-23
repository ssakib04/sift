import uuid
from datetime import UTC, datetime

import pytest

from app.services.cv_upload import UPLOAD_LIMIT, UploadError, UploadedCv, check_upload_count, upload_job_cvs
from app.services.screening import JobMailKey, contact_email


def test_contact_email_keeps_the_sender_address() -> None:
    found = contact_email(
        "sender@example.com",
        {"email": "cv@example.com"},
        "Reach me at other@example.com",
    )
    assert found == "sender@example.com"


def test_contact_email_uses_the_address_on_the_cv() -> None:
    found = contact_email("", {"email": "Ada <ada@example.com>"}, "no address here")
    assert found == "ada@example.com"


def test_contact_email_reads_the_cv_text_when_extraction_is_blank() -> None:
    found = contact_email("", {"email": ""}, "Email: jordan@example.com\nSkills: Python")
    assert found == "jordan@example.com"


def test_upload_count_rejects_an_empty_batch_and_more_than_twenty() -> None:
    with pytest.raises(UploadError) as empty:
        check_upload_count(0)
    assert empty.value.code == "CV_UPLOAD_EMPTY"
    with pytest.raises(UploadError) as over:
        check_upload_count(UPLOAD_LIMIT + 1)
    assert over.value.code == "CV_UPLOAD_LIMIT"
    check_upload_count(UPLOAD_LIMIT)


class _Session:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


def _key() -> JobMailKey:
    return JobMailKey(
        job_id=uuid.uuid4(),
        mail_subject="Engineer",
        version_id=uuid.uuid4(),
        title="Engineer",
        locked_at=datetime(2026, 10, 1, tzinfo=UTC),
    )


@pytest.mark.asyncio
async def test_upload_scores_a_pdf_and_skips_a_file_that_is_not_a_cv(monkeypatch: pytest.MonkeyPatch) -> None:
    key = _key()
    seen: list[dict[str, object]] = []
    notices: list[str] = []

    async def fake_keys(_session: object) -> list[JobMailKey]:
        return [key]

    async def fake_accept(*_args: object, **kwargs: object) -> str:
        seen.append(kwargs)
        return "scored"

    async def fake_notice(_session: object, *, job_id: object, summary: str, now: object) -> None:
        assert job_id == key.job_id
        assert now is not None
        notices.append(summary)

    monkeypatch.setattr("app.services.cv_upload.load_mail_keys", fake_keys)
    monkeypatch.setattr("app.services.cv_upload.accept_cv", fake_accept)
    monkeypatch.setattr("app.services.cv_upload.create_face_embedder", lambda _settings: object())
    monkeypatch.setattr("app.services.cv_upload.record_ranking_notice", fake_notice)
    session = _Session()
    result = await upload_job_cvs(
        session,  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        llm=object(),  # type: ignore[arg-type]
        embedder=object(),  # type: ignore[arg-type]
        job_id=key.job_id,
        files=[
            UploadedCv("notes.txt", b"hello"),
            UploadedCv("ada.pdf", b"%PDF-1.4 sample"),
        ],
    )
    assert [item.outcome for item in result.items] == ["invalid", "scored"]
    assert result.scored == 1
    assert result.invalid == 1
    assert session.commits == 2
    assert notices[0].startswith("1 CV scored for Engineer.")
    assert "choose who to invite" in notices[0]
    assert seen[0]["version_id"] == key.version_id
    assert seen[0]["from_address"] == ""
    assert str(seen[0]["message_id"]).startswith("upload-")


@pytest.mark.asyncio
async def test_upload_refuses_a_job_that_is_not_locked(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_keys(_session: object) -> list[JobMailKey]:
        return []

    monkeypatch.setattr("app.services.cv_upload.load_mail_keys", fake_keys)
    with pytest.raises(UploadError) as error:
        await upload_job_cvs(
            _Session(),  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
            llm=object(),  # type: ignore[arg-type]
            embedder=object(),  # type: ignore[arg-type]
            job_id=uuid.uuid4(),
            files=[UploadedCv("ada.pdf", b"%PDF-1.4 sample")],
        )
    assert error.value.code == "JOB_NOT_LOCKED"


@pytest.mark.asyncio
async def test_one_failed_cv_does_not_stop_the_rest(monkeypatch: pytest.MonkeyPatch) -> None:
    key = _key()
    calls = 0

    async def fake_keys(_session: object) -> list[JobMailKey]:
        return [key]

    async def fake_accept(*_args: object, **_kwargs: object) -> str:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("score failed")
        return "duplicate"

    monkeypatch.setattr("app.services.cv_upload.load_mail_keys", fake_keys)
    monkeypatch.setattr("app.services.cv_upload.accept_cv", fake_accept)
    monkeypatch.setattr("app.services.cv_upload.create_face_embedder", lambda _settings: object())
    session = _Session()
    result = await upload_job_cvs(
        session,  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        llm=object(),  # type: ignore[arg-type]
        embedder=object(),  # type: ignore[arg-type]
        job_id=key.job_id,
        files=[
            UploadedCv("one.pdf", b"%PDF-1.4 one"),
            UploadedCv("two.pdf", b"%PDF-1.4 two"),
        ],
    )
    assert [item.outcome for item in result.items] == ["failed", "duplicate"]
    assert session.rollbacks == 1
    assert session.commits == 1
