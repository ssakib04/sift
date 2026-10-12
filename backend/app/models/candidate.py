import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.job import JobVersion


class Candidate(Base):
    __tablename__ = "candidates"
    __table_args__ = (UniqueConstraint("job_version_id", "content_sha256", name="uq_candidate_version_sha"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    job_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("job_versions.id", ondelete="CASCADE"),
        index=True,
    )
    email: Mapped[str] = mapped_column(String(320))
    full_name: Mapped[str] = mapped_column(String(255))
    content_sha256: Mapped[str] = mapped_column(String(64))
    source_message_id: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    version: Mapped[JobVersion] = relationship()
    document: Mapped["CandidateDocument | None"] = relationship(
        back_populates="candidate",
        cascade="all, delete-orphan",
        uselist=False,
    )
    parse_result: Mapped["CandidateParseResult | None"] = relationship(
        back_populates="candidate",
        cascade="all, delete-orphan",
        uselist=False,
    )
    snapshot: Mapped["ScoreSnapshot | None"] = relationship(
        back_populates="candidate",
        cascade="all, delete-orphan",
        uselist=False,
    )
    magic_link: Mapped["MagicLink | None"] = relationship(
        back_populates="candidate",
        cascade="all, delete-orphan",
        uselist=False,
    )
    interview_session: Mapped["InterviewSession | None"] = relationship(
        back_populates="candidate",
        cascade="all, delete-orphan",
        uselist=False,
    )


class CandidateDocument(Base):
    __tablename__ = "candidate_documents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("candidates.id", ondelete="CASCADE"),
        unique=True,
    )
    filename: Mapped[str] = mapped_column(String(255))
    media_type: Mapped[str] = mapped_column(String(127))
    storage_path: Mapped[str] = mapped_column(String(512))
    size_bytes: Mapped[int] = mapped_column(Integer)

    candidate: Mapped[Candidate] = relationship(back_populates="document")


class CandidateParseResult(Base):
    __tablename__ = "candidate_parse_results"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("candidates.id", ondelete="CASCADE"),
        unique=True,
    )
    status: Mapped[str] = mapped_column(String(32))
    parse_method: Mapped[str] = mapped_column(String(32))
    parse_confidence: Mapped[float] = mapped_column(Float)
    warnings: Mapped[list[str]] = mapped_column(JSON)
    raw_text: Mapped[str] = mapped_column(Text)

    candidate: Mapped[Candidate] = relationship(back_populates="parse_result")


class ScoreSnapshot(Base):
    __tablename__ = "score_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("candidates.id", ondelete="CASCADE"),
        unique=True,
    )
    job_version_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    aggregate_score: Mapped[float] = mapped_column(Float)
    must_have_ratio: Mapped[float] = mapped_column(Float)
    technical_score: Mapped[float] = mapped_column(Float)
    experience_score: Mapped[float] = mapped_column(Float)
    qualification_score: Mapped[float] = mapped_column(Float)
    fairness_flags: Mapped[list[str]] = mapped_column(JSON)
    justifications: Mapped[list[str]] = mapped_column(JSON)
    llm_tier: Mapped[str] = mapped_column(String(32))
    fallback_used: Mapped[bool]
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    candidate: Mapped[Candidate] = relationship(back_populates="snapshot")
    evaluations: Mapped[list["QueryEvaluation"]] = relationship(
        back_populates="snapshot",
        cascade="all, delete-orphan",
    )


class QueryEvaluation(Base):
    __tablename__ = "query_evaluations"
    __table_args__ = (UniqueConstraint("snapshot_id", "query_id", name="uq_snapshot_query"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("score_snapshots.id", ondelete="CASCADE"),
        index=True,
    )
    query_id: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(32))
    confidence: Mapped[float] = mapped_column(Float)
    evidence: Mapped[str] = mapped_column(Text)
    semantic_score: Mapped[float] = mapped_column(Float)

    snapshot: Mapped[ScoreSnapshot] = relationship(back_populates="evaluations")


class MagicLink(Base):
    __tablename__ = "magic_links"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("candidates.id", ondelete="CASCADE"),
        unique=True,
    )
    token: Mapped[str] = mapped_column(String(128), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    candidate: Mapped[Candidate] = relationship(back_populates="magic_link")


class InterviewSession(Base):
    __tablename__ = "interview_sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("candidates.id", ondelete="CASCADE"),
        unique=True,
    )
    job_version_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    status: Mapped[str] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consented_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    processing_status: Mapped[str] = mapped_column(String(32), default="", server_default="")
    copilot_explored: Mapped[list[str]] = mapped_column(JSON, default=list)
    copilot_gaps: Mapped[list[str]] = mapped_column(JSON, default=list)
    copilot_question: Mapped[str] = mapped_column(Text, default="", server_default="")
    copilot_turn_count: Mapped[int] = mapped_column(Integer, default=-1, server_default="-1")

    candidate: Mapped[Candidate] = relationship(back_populates="interview_session")
    transcript_segments: Mapped[list["TranscriptSegment"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
    )
    analysis: Mapped["InterviewAnalysis | None"] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        uselist=False,
    )


class TranscriptSegment(Base):
    __tablename__ = "transcript_segments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("interview_sessions.id", ondelete="CASCADE"),
        index=True,
    )
    speaker: Mapped[str] = mapped_column(String(32))
    start_time: Mapped[float] = mapped_column(Float)
    end_time: Mapped[float] = mapped_column(Float)
    text: Mapped[str] = mapped_column(Text)
    confidence: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    session: Mapped[InterviewSession] = relationship(back_populates="transcript_segments")


class InterviewAnalysis(Base):
    __tablename__ = "interview_analyses"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("interview_sessions.id", ondelete="CASCADE"),
        unique=True,
    )
    relevance: Mapped[float] = mapped_column(Float)
    technical_accuracy: Mapped[float] = mapped_column(Float)
    completeness: Mapped[float] = mapped_column(Float)
    articulation: Mapped[float] = mapped_column(Float)
    gaps: Mapped[list[str]] = mapped_column(JSON)
    summary: Mapped[str] = mapped_column(Text)
    llm_tier: Mapped[str] = mapped_column(String(32))
    fallback_used: Mapped[bool]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    session: Mapped[InterviewSession] = relationship(back_populates="analysis")


class IntakeMessage(Base):
    __tablename__ = "intake_messages"

    message_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    status: Mapped[str] = mapped_column(String(32))
    job_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
