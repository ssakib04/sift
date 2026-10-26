from uuid import uuid4

import pymupdf

from app.core.session_tokens import SessionClaims
from app.services.interview_packet import (
    InterviewPacket,
    PacketLine,
    load_interview_packet,
    packet_filename,
    render_packet_html,
    render_packet_pdf,
)
from app.services.interview_rules import InterviewError


def _packet() -> InterviewPacket:
    return InterviewPacket(
        full_name="Ada <script>",
        job_title="Backend Engineer",
        cv_text="Built REST APIs.\n<script>alert(1)</script>",
        questions=["How did you design the API?"],
        lines=[PacketLine(speaker="candidate", text="I kept the handlers small.")],
    )


def test_packet_html_escapes_cv_markup() -> None:
    html = render_packet_html(_packet())
    assert "Ada &lt;script&gt;" in html
    assert "<script>" not in html
    assert "How did you design the API?" in html
    assert "I kept the handlers small." in html
    assert "Candidate." in html


def test_packet_html_names_missing_sections() -> None:
    html = render_packet_html(
        InterviewPacket(full_name="Omar Ali", job_title="Analyst", cv_text="", questions=[], lines=[])
    )
    assert "no parsed text" in html
    assert "No checklist questions" in html
    assert "No transcript lines" in html


def test_packet_pdf_keeps_the_cv_question_and_answer() -> None:
    data = render_packet_pdf(_packet())
    assert data.startswith(b"%PDF")
    document = pymupdf.open(stream=data, filetype="pdf")
    text = "".join(page.get_text() for page in document)
    document.close()
    assert "Ada <script>" in text
    assert "How did you design the API?" in text
    assert "I kept the handlers small." in text
    assert "Backend Engineer" in text


def test_packet_filename_uses_the_candidate_name() -> None:
    assert packet_filename(_packet(), "pdf") == "ada-script-interview.pdf"


async def test_candidate_cannot_open_the_packet() -> None:
    claims = SessionClaims(role="candidate", candidate_id=uuid4(), job_id=uuid4(), session_id=uuid4())
    try:
        await load_interview_packet(None, claims)  # type: ignore[arg-type]
    except InterviewError as exc:
        assert exc.status_code == 403
        assert exc.code == "INTERVIEW_FORBIDDEN"
        return
    raise AssertionError("expected a recruiter-only refusal")
