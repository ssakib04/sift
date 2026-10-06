import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    versions: Mapped[list["JobVersion"]] = relationship(
        back_populates="job",
        cascade="all, delete-orphan",
    )


class JobVersion(Base):
    __tablename__ = "job_versions"
    __table_args__ = (UniqueConstraint("job_id", "version_number", name="uq_job_version_number"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    job_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    version_number: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), index=True)
    seniority: Mapped[str] = mapped_column(String(32))
    required_skills: Mapped[list[str]] = mapped_column(JSON)
    preferred_skills: Mapped[list[str]] = mapped_column(JSON)
    qualifications: Mapped[str] = mapped_column(Text)
    minimum_years: Mapped[int] = mapped_column(Integer)
    technical_weight: Mapped[float] = mapped_column(Float)
    experience_weight: Mapped[float] = mapped_column(Float)
    qualification_weight: Mapped[float] = mapped_column(Float)
    contract: Mapped[str] = mapped_column(String(32))
    category: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text)
    policy_excerpts: Mapped[list[str]] = mapped_column(JSON)
    llm_tier: Mapped[str] = mapped_column(String(32))
    fallback_used: Mapped[bool]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    job: Mapped[Job] = relationship(back_populates="versions")
    queries: Mapped[list["JobChecklistQuery"]] = relationship(
        back_populates="version",
        cascade="all, delete-orphan",
    )
    posting: Mapped["JobPosting | None"] = relationship(
        back_populates="version",
        cascade="all, delete-orphan",
        uselist=False,
    )


class JobChecklistQuery(Base):
    __tablename__ = "job_checklist_queries"
    __table_args__ = (UniqueConstraint("version_id", "query_id", name="uq_version_query_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("job_versions.id", ondelete="CASCADE"),
        index=True,
    )
    query_id: Mapped[str] = mapped_column(String(8))
    question: Mapped[str] = mapped_column(Text)
    dimension: Mapped[str] = mapped_column(String(32))
    requirement_type: Mapped[str] = mapped_column(String(32))
    weight: Mapped[float] = mapped_column(Float)
    evidence_hints: Mapped[list[str]] = mapped_column(JSON)
    scoring_rubric: Mapped[str] = mapped_column(Text)

    version: Mapped[JobVersion] = relationship(back_populates="queries")


class JobPosting(Base):
    __tablename__ = "job_postings"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    version_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("job_versions.id", ondelete="CASCADE"),
        unique=True,
    )
    provider: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32))
    apply_url: Mapped[str] = mapped_column(String(512))
    detail: Mapped[str | None] = mapped_column(String(128), nullable=True)

    version: Mapped[JobVersion] = relationship(back_populates="posting")
