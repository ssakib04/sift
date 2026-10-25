import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.job import Job, JobVersion

FACE_DIMENSIONS = 512


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
    quiz_attempt: Mapped["McqAttempt | None"] = relationship(
        back_populates="candidate",
        cascade="all, delete-orphan",
        uselist=False,
    )
    consolidated_assessment: Mapped["ConsolidatedAssessment | None"] = relationship(
        back_populates="candidate",
        cascade="all, delete-orphan",
        uselist=False,
    )
    profile: Mapped["CandidateProfile | None"] = relationship(
        back_populates="candidate",
        cascade="all, delete-orphan",
        uselist=False,
    )
    face: Mapped["CandidateFace | None"] = relationship(
        back_populates="candidate",
        cascade="all, delete-orphan",
        uselist=False,
    )
    cv_claims: Mapped[list["CvClaim"]] = relationship(
        back_populates="candidate",
        cascade="all, delete-orphan",
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


class ApplicantNotification(Base):
    """One recruiter alert for an applicant who has just entered the system."""

    __tablename__ = "applicant_notifications"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    candidate_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("candidates.id", ondelete="CASCADE"),
        unique=True,
        nullable=True,
    )
    job_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=True,
    )
    summary: Mapped[str] = mapped_column(Text, default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    candidate: Mapped[Candidate | None] = relationship()
    job: Mapped[Job | None] = relationship()


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
    biometric_consented_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    face_admitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    conductor: Mapped[str] = mapped_column(String(16), default="", server_default="")
    report_progress: Mapped[dict[str, str]] = mapped_column(JSON, default=dict, server_default="{}")
    scheduled_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scheduled_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    calendar_event_id: Mapped[str] = mapped_column(String(255), default="", server_default="")
    calendar_url: Mapped[str] = mapped_column(Text, default="", server_default="")

    candidate: Mapped[Candidate] = relationship(back_populates="interview_session")
    face_check: Mapped["FaceCheck | None"] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        uselist=False,
    )
    transcript_segments: Mapped[list["TranscriptSegment"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
    )
    analysis: Mapped["InterviewAnalysis | None"] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        uselist=False,
    )
    claim_verification: Mapped["ClaimVerification | None"] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        uselist=False,
    )
    performance: Mapped["InterviewPerformance | None"] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        uselist=False,
    )
    quality: Mapped["InterviewQuality | None"] = relationship(
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
    is_final: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
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
    discrepancies: Mapped[list[str]] = mapped_column(JSON, default=list)
    summary: Mapped[str] = mapped_column(Text)
    justifications: Mapped[list[dict[str, str]]] = mapped_column(JSON, default=list)
    llm_tier: Mapped[str] = mapped_column(String(32))
    fallback_used: Mapped[bool]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    session: Mapped[InterviewSession] = relationship(back_populates="analysis")
    pairs: Mapped[list["QAPair"]] = relationship(
        back_populates="analysis",
        cascade="all, delete-orphan",
    )


class QAPair(Base):
    __tablename__ = "qa_pairs"
    __table_args__ = (UniqueConstraint("analysis_id", "pair_id", name="uq_analysis_pair_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("interview_analyses.id", ondelete="CASCADE"),
        index=True,
    )
    pair_id: Mapped[str] = mapped_column(String(16))
    sequence: Mapped[int] = mapped_column(Integer)
    question: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    intent: Mapped[str] = mapped_column(String(32))
    start_time: Mapped[float] = mapped_column(Float)
    end_time: Mapped[float] = mapped_column(Float)
    citation: Mapped[str] = mapped_column(String(80))
    query_ids: Mapped[list[str]] = mapped_column(JSON)
    relevance: Mapped[float] = mapped_column(Float)
    technical_accuracy: Mapped[float] = mapped_column(Float)
    completeness: Mapped[float] = mapped_column(Float)
    articulation: Mapped[float] = mapped_column(Float)
    notes: Mapped[dict[str, str]] = mapped_column(JSON)

    analysis: Mapped[InterviewAnalysis] = relationship(back_populates="pairs")


class InterviewPerformance(Base):
    __tablename__ = "interview_performances"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("interview_sessions.id", ondelete="CASCADE"),
        unique=True,
    )
    overall_score: Mapped[float] = mapped_column(Float)
    summary: Mapped[str] = mapped_column(Text)
    llm_tier: Mapped[str] = mapped_column(String(32))
    fallback_used: Mapped[bool]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    session: Mapped[InterviewSession] = relationship(back_populates="performance")
    dimensions: Mapped[list["InterviewPerformanceDimension"]] = relationship(
        back_populates="performance",
        cascade="all, delete-orphan",
    )


class InterviewPerformanceDimension(Base):
    __tablename__ = "interview_performance_dimensions"
    __table_args__ = (UniqueConstraint("performance_id", "dimension_key", name="uq_performance_dimension"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    performance_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("interview_performances.id", ondelete="CASCADE"),
        index=True,
    )
    dimension_key: Mapped[str] = mapped_column(String(32))
    label: Mapped[str] = mapped_column(String(64))
    score: Mapped[float] = mapped_column(Float)
    evidence: Mapped[str] = mapped_column(Text)
    note: Mapped[str] = mapped_column(Text)
    sequence: Mapped[int] = mapped_column(Integer)

    performance: Mapped[InterviewPerformance] = relationship(back_populates="dimensions")


class InterviewQuality(Base):
    __tablename__ = "interview_qualities"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("interview_sessions.id", ondelete="CASCADE"),
        unique=True,
    )
    overall_score: Mapped[float] = mapped_column(Float)
    summary: Mapped[str] = mapped_column(Text)
    interviewer_share: Mapped[float] = mapped_column(Float)
    candidate_share: Mapped[float] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    session: Mapped[InterviewSession] = relationship(back_populates="quality")
    dimensions: Mapped[list["InterviewQualityDimension"]] = relationship(
        back_populates="quality",
        cascade="all, delete-orphan",
    )
    recommendations: Mapped[list["InterviewQualityRecommendation"]] = relationship(
        back_populates="quality",
        cascade="all, delete-orphan",
    )


class InterviewQualityDimension(Base):
    __tablename__ = "interview_quality_dimensions"
    __table_args__ = (UniqueConstraint("quality_id", "dimension_key", name="uq_quality_dimension"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    quality_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("interview_qualities.id", ondelete="CASCADE"),
        index=True,
    )
    dimension_key: Mapped[str] = mapped_column(String(32))
    label: Mapped[str] = mapped_column(String(64))
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    note: Mapped[str] = mapped_column(Text)
    sequence: Mapped[int] = mapped_column(Integer)

    quality: Mapped[InterviewQuality] = relationship(back_populates="dimensions")


class InterviewQualityRecommendation(Base):
    __tablename__ = "interview_quality_recommendations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    quality_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("interview_qualities.id", ondelete="CASCADE"),
        index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(32))
    text: Mapped[str] = mapped_column(Text)

    quality: Mapped[InterviewQuality] = relationship(back_populates="recommendations")


class McqAttempt(Base):
    __tablename__ = "mcq_attempts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("candidates.id", ondelete="CASCADE"),
        unique=True,
    )
    job_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("job_versions.id", ondelete="CASCADE"),
        index=True,
    )
    questions: Mapped[list[dict[str, object]]] = mapped_column(JSON)
    answers: Mapped[list[int | None] | None] = mapped_column(JSON, nullable=True)
    correct_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    time_limit_seconds: Mapped[int] = mapped_column(Integer)
    llm_tier: Mapped[str] = mapped_column(String(32))
    fallback_used: Mapped[bool]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    candidate: Mapped[Candidate] = relationship(back_populates="quiz_attempt")


class ConsolidatedAssessment(Base):
    __tablename__ = "consolidated_assessments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("candidates.id", ondelete="CASCADE"),
        unique=True,
    )
    job_version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("job_versions.id", ondelete="CASCADE"),
        index=True,
    )
    overall_suitability: Mapped[str] = mapped_column(String(32))
    overall_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    narrative: Mapped[str] = mapped_column(Text)
    cv_weight: Mapped[float] = mapped_column(Float)
    mcq_weight: Mapped[float] = mapped_column(Float)
    interview_weight: Mapped[float] = mapped_column(Float)
    llm_tier: Mapped[str] = mapped_column(String(32))
    fallback_used: Mapped[bool]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    candidate: Mapped[Candidate] = relationship(back_populates="consolidated_assessment")
    component_scores: Mapped[list["AssessmentComponentScore"]] = relationship(
        back_populates="assessment",
        cascade="all, delete-orphan",
    )
    strengths: Mapped[list["AssessmentStrength"]] = relationship(
        back_populates="assessment",
        cascade="all, delete-orphan",
    )
    weaknesses: Mapped[list["AssessmentWeakness"]] = relationship(
        back_populates="assessment",
        cascade="all, delete-orphan",
    )
    evidence_links: Mapped[list["EvidenceLink"]] = relationship(
        back_populates="assessment",
        cascade="all, delete-orphan",
    )


class AssessmentComponentScore(Base):
    __tablename__ = "assessment_component_scores"
    __table_args__ = (UniqueConstraint("assessment_id", "component", name="uq_assessment_component"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("consolidated_assessments.id", ondelete="CASCADE"),
        index=True,
    )
    component: Mapped[str] = mapped_column(String(32))
    score: Mapped[float | None] = mapped_column(Float, nullable=True)

    assessment: Mapped[ConsolidatedAssessment] = relationship(back_populates="component_scores")


class AssessmentStrength(Base):
    __tablename__ = "assessment_strengths"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("consolidated_assessments.id", ondelete="CASCADE"),
        index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)

    assessment: Mapped[ConsolidatedAssessment] = relationship(back_populates="strengths")


class AssessmentWeakness(Base):
    __tablename__ = "assessment_weaknesses"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("consolidated_assessments.id", ondelete="CASCADE"),
        index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)

    assessment: Mapped[ConsolidatedAssessment] = relationship(back_populates="weaknesses")


class EvidenceLink(Base):
    __tablename__ = "evidence_links"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("consolidated_assessments.id", ondelete="CASCADE"),
        index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer)
    claim: Mapped[str] = mapped_column(Text)
    source_type: Mapped[str] = mapped_column(String(32))
    source_reference: Mapped[str] = mapped_column(String(80))
    evidence: Mapped[str] = mapped_column(Text)

    assessment: Mapped[ConsolidatedAssessment] = relationship(back_populates="evidence_links")


class CandidateProfile(Base):
    __tablename__ = "candidate_profiles"

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("candidates.id", ondelete="CASCADE"),
        primary_key=True,
    )
    headline: Mapped[str] = mapped_column(Text)
    skills: Mapped[list[str]] = mapped_column(JSON)
    experience_years: Mapped[float] = mapped_column(Float)

    candidate: Mapped[Candidate] = relationship(back_populates="profile")


class CandidateFace(Base):
    __tablename__ = "candidate_faces"

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("candidates.id", ondelete="CASCADE"),
        primary_key=True,
    )
    storage_path: Mapped[str] = mapped_column(String(512))
    embedding: Mapped[list[float]] = mapped_column(Vector(FACE_DIMENSIONS))
    det_score: Mapped[float] = mapped_column(Float)
    enrolled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    candidate: Mapped[Candidate] = relationship(back_populates="face")


class FaceCheck(Base):
    __tablename__ = "face_checks"

    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("interview_sessions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    status: Mapped[str] = mapped_column(String(32))
    matched_candidate_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid,
        ForeignKey("candidates.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    similarity: Mapped[float | None] = mapped_column(Float, nullable=True)
    invited_similarity: Mapped[float | None] = mapped_column(Float, nullable=True)
    ambiguous: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    samples: Mapped[list[dict[str, object]]] = mapped_column(JSON, default=list)
    concluded: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    session: Mapped[InterviewSession] = relationship(back_populates="face_check")


class CvClaim(Base):
    __tablename__ = "cv_claims"
    __table_args__ = (UniqueConstraint("candidate_id", "claim_id", name="uq_candidate_claim"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    candidate_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("candidates.id", ondelete="CASCADE"),
        index=True,
    )
    claim_id: Mapped[str] = mapped_column(String(8))
    kind: Mapped[str] = mapped_column(String(32))
    statement: Mapped[str] = mapped_column(Text)
    subject: Mapped[str] = mapped_column(Text)
    cv_quote: Mapped[str] = mapped_column(Text)
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)

    candidate: Mapped[Candidate] = relationship(back_populates="cv_claims")


class ClaimVerification(Base):
    __tablename__ = "claim_verifications"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("interview_sessions.id", ondelete="CASCADE"),
        unique=True,
    )
    llm_tier: Mapped[str] = mapped_column(String(32))
    fallback_used: Mapped[bool]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    session: Mapped[InterviewSession] = relationship(back_populates="claim_verification")
    flags: Mapped[list["ClaimFlag"]] = relationship(
        back_populates="verification",
        cascade="all, delete-orphan",
    )


class ClaimFlag(Base):
    __tablename__ = "claim_flags"
    __table_args__ = (UniqueConstraint("verification_id", "claim_id", name="uq_verification_claim"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    verification_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("claim_verifications.id", ondelete="CASCADE"),
        index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer)
    claim_id: Mapped[str] = mapped_column(String(8))
    kind: Mapped[str] = mapped_column(String(32))
    statement: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32))
    cv_quote: Mapped[str] = mapped_column(Text)
    interview_quote: Mapped[str] = mapped_column(Text)
    follow_up: Mapped[str] = mapped_column(Text)

    verification: Mapped[ClaimVerification] = relationship(back_populates="flags")


class IntakeMessage(Base):
    __tablename__ = "intake_messages"

    message_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    status: Mapped[str] = mapped_column(String(32))
    job_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
