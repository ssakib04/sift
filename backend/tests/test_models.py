"""Unit tests for SQLModel entities and database initialization."""

import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session as DBSession
from sqlmodel import create_engine

from app.core.config import Settings
from app.core.db import create_db_engine, get_session, init_db, normalize_database_url
from app.models import Assessment, CV, Candidate, JobProfile, Score, Session, Transcript
from app.models.cv import EMBEDDING_DIMENSIONS

EXPECTED_TABLES = {
    "job_profile",
    "candidate",
    "cv",
    "score",
    "session",
    "transcript",
    "assessment",
}


def _sqlite_engine():
    return create_engine("sqlite://", connect_args={"check_same_thread": False})


def _dimensional_scores() -> dict[str, float]:
    return {"technical": 80.0, "communication": 70.0, "problem-solving": 75.0}


def test_settings_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    """Settings fall back to the local development database and Redis."""
    for name in (
        "PROJECT_NAME",
        "POSTGRES_SERVER",
        "POSTGRES_PORT",
        "POSTGRES_HOST_PORT",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
        "DATABASE_URL",
        "REDIS_URL",
        "ANTHROPIC_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)

    settings = Settings(_env_file=None)

    assert settings.PROJECT_NAME == "Sift"
    assert settings.POSTGRES_SERVER == "localhost"
    assert settings.POSTGRES_PORT == 5432
    assert settings.POSTGRES_HOST_PORT == 5433
    assert settings.POSTGRES_USER == "sift"
    assert settings.POSTGRES_PASSWORD == "sift_secret"
    assert settings.POSTGRES_DB == "sift_db"
    assert settings.DATABASE_URL == "postgresql://sift:sift_secret@localhost:5433/sift_db"
    assert settings.REDIS_URL == "redis://localhost:6379/0"
    assert settings.ANTHROPIC_API_KEY == "your_anthropic_api_key_here"


def test_normalize_database_url_pins_psycopg2() -> None:
    assert (
        normalize_database_url("postgresql://sift:sift_secret@localhost:5432/sift_db")
        == "postgresql+psycopg2://sift:sift_secret@localhost:5432/sift_db"
    )
    assert normalize_database_url("sqlite://") == "sqlite://"


def test_job_profile_instantiation() -> None:
    profile = JobProfile(
        title="Backend Engineer",
        description="Build screening APIs.",
        requirements=["Python", "FastAPI"],
    )

    assert isinstance(profile.id, uuid.UUID)
    assert profile.title == "Backend Engineer"
    assert profile.requirements == ["Python", "FastAPI"]
    assert profile.created_at.tzinfo is not None
    assert profile.updated_at.tzinfo is not None


def test_job_profile_rejects_blank_title() -> None:
    with pytest.raises(ValidationError):
        JobProfile(title="", description="Build screening APIs.")


def test_candidate_instantiation() -> None:
    candidate = Candidate(full_name="Ada Lovelace", email="ada@example.com", phone=None)

    assert isinstance(candidate.id, uuid.UUID)
    assert candidate.email == "ada@example.com"
    assert candidate.phone is None
    assert candidate.created_at.tzinfo is not None


def test_candidate_rejects_invalid_email() -> None:
    with pytest.raises(ValidationError):
        Candidate(full_name="Ada Lovelace", email="not-an-email")


def test_cv_instantiation() -> None:
    candidate_id = uuid.uuid4()
    cv = CV(
        candidate_id=candidate_id,
        file_path="/data/cvs/raw/ada.pdf",
        raw_text="Built RAG pipelines.",
        embedding=[0.1] * EMBEDDING_DIMENSIONS,
    )

    assert cv.candidate_id == candidate_id
    assert cv.embedding is not None
    assert len(cv.embedding) == EMBEDDING_DIMENSIONS
    assert cv.created_at.tzinfo is not None


def test_cv_rejects_wrong_embedding_length() -> None:
    with pytest.raises(ValidationError):
        CV(
            candidate_id=uuid.uuid4(),
            file_path="/data/cvs/raw/ada.pdf",
            raw_text="Built RAG pipelines.",
            embedding=[0.1, 0.2],
        )


def test_score_instantiation() -> None:
    score = Score(
        candidate_id=uuid.uuid4(),
        job_profile_id=uuid.uuid4(),
        dimensional_scores=_dimensional_scores(),
        overall_score=76.5,
        summary="Strong API background.",
    )

    assert score.overall_score == 76.5
    assert score.dimensional_scores["problem-solving"] == 75.0


def test_score_rejects_incomplete_dimensions_and_out_of_range_total() -> None:
    with pytest.raises(ValidationError):
        Score(
            candidate_id=uuid.uuid4(),
            job_profile_id=uuid.uuid4(),
            dimensional_scores={"technical": 80.0},
            overall_score=80.0,
            summary="Incomplete.",
        )
    with pytest.raises(ValidationError):
        Score(
            candidate_id=uuid.uuid4(),
            job_profile_id=uuid.uuid4(),
            dimensional_scores=_dimensional_scores(),
            overall_score=140.0,
            summary="Out of range.",
        )


def test_session_instantiation() -> None:
    started_at = datetime(2026, 10, 4, tzinfo=timezone.utc)
    interview = Session(
        candidate_id=uuid.uuid4(),
        job_profile_id=uuid.uuid4(),
        status="scheduled",
        started_at=started_at,
        ended_at=None,
    )

    assert interview.status == "scheduled"
    assert interview.started_at == started_at
    assert interview.ended_at is None


def test_session_rejects_unknown_status() -> None:
    with pytest.raises(ValidationError):
        Session(
            candidate_id=uuid.uuid4(),
            job_profile_id=uuid.uuid4(),
            status="cancelled",
        )


def test_transcript_instantiation() -> None:
    turn = Transcript(
        session_id=uuid.uuid4(),
        speaker="candidate",
        text="I shipped a pgvector search service.",
        timestamp_ms=1500,
    )

    assert turn.speaker == "candidate"
    assert turn.timestamp_ms == 1500


def test_transcript_rejects_invalid_speaker_and_negative_timestamp() -> None:
    with pytest.raises(ValidationError):
        Transcript(
            session_id=uuid.uuid4(),
            speaker="observer",
            text="Hello",
            timestamp_ms=0,
        )
    with pytest.raises(ValidationError):
        Transcript(
            session_id=uuid.uuid4(),
            speaker="interviewer",
            text="Hello",
            timestamp_ms=-1,
        )


def test_assessment_instantiation() -> None:
    report = {"overall_suitability": "strong_fit", "overall_score": 83.4}
    assessment = Assessment(session_id=uuid.uuid4(), consolidated_report=report)

    assert assessment.consolidated_report == report
    assert isinstance(assessment.id, uuid.UUID)
    assert assessment.created_at.tzinfo is not None


def test_assessment_rejects_non_object_report() -> None:
    with pytest.raises(ValidationError):
        Assessment(session_id=uuid.uuid4(), consolidated_report=["not", "an", "object"])


def test_init_db_creates_tables_on_sqlite() -> None:
    sqlite_engine = _sqlite_engine()

    init_db(sqlite_engine)
    init_db(sqlite_engine)

    table_names = set(inspect(sqlite_engine).get_table_names())
    assert table_names == EXPECTED_TABLES
    cv_columns = {column["name"] for column in inspect(sqlite_engine).get_columns("cv")}
    assert "embedding" in cv_columns


def test_init_db_enables_pgvector_on_postgresql() -> None:
    bind = MagicMock()
    bind.dialect.name = "postgresql"
    connection = MagicMock()
    bind.begin.return_value.__enter__.return_value = connection

    with patch("app.core.db.SQLModel.metadata.create_all") as create_all:
        init_db(bind)

    statement = connection.execute.call_args.args[0]
    assert "CREATE EXTENSION IF NOT EXISTS vector" in str(statement)
    create_all.assert_called_once_with(bind)


def test_get_session_round_trips_related_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    sqlite_engine = _sqlite_engine()
    init_db(sqlite_engine)
    monkeypatch.setattr("app.core.db.engine", sqlite_engine)

    generator = get_session()
    session = next(generator)
    try:
        profile = JobProfile(
            title="Backend Engineer",
            description="Build screening APIs.",
            requirements=["Python"],
        )
        candidate = Candidate(full_name="Grace Hopper", email="grace@example.com")
        session.add(profile)
        session.add(candidate)
        session.commit()
        session.refresh(profile)
        session.refresh(candidate)

        cv = CV(
            candidate_id=candidate.id,
            file_path="/data/cvs/raw/grace.pdf",
            raw_text="Designed compilers and databases.",
            embedding=[0.25] * EMBEDDING_DIMENSIONS,
        )
        score = Score(
            candidate_id=candidate.id,
            job_profile_id=profile.id,
            dimensional_scores=_dimensional_scores(),
            overall_score=88.0,
            summary="Exceptional systems background.",
        )
        interview = Session(
            candidate_id=candidate.id,
            job_profile_id=profile.id,
            status="in_progress",
        )
        session.add(cv)
        session.add(score)
        session.add(interview)
        session.commit()
        session.refresh(interview)

        transcript = Transcript(
            session_id=interview.id,
            speaker="interviewer",
            text="Walk through a production incident.",
            timestamp_ms=3200,
        )
        assessment = Assessment(
            session_id=interview.id,
            consolidated_report={"overall_suitability": "strong_fit"},
        )
        session.add(transcript)
        session.add(assessment)
        session.commit()

        stored_cv = session.get(CV, cv.id)
        assert stored_cv is not None
        assert stored_cv.embedding == [0.25] * EMBEDDING_DIMENSIONS
        assert session.get(Score, score.id) is not None
        assert session.get(Transcript, transcript.id) is not None
        assert session.get(Assessment, assessment.id) is not None
    finally:
        generator.close()


def test_candidate_email_is_unique() -> None:
    sqlite_engine = _sqlite_engine()
    init_db(sqlite_engine)

    with DBSession(sqlite_engine) as session:
        session.add(Candidate(full_name="Ada Lovelace", email="ada@example.com"))
        session.add(Candidate(full_name="Augusta Ada", email="ada@example.com"))
        with pytest.raises(IntegrityError):
            session.commit()


def test_create_db_engine_uses_configured_sqlite_url() -> None:
    sqlite_engine = create_db_engine("sqlite://")
    assert sqlite_engine.dialect.name == "sqlite"
