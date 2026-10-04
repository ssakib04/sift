"""SQLModel engine, session dependency, and database startup."""

from collections.abc import Generator

from sqlalchemy import Engine, text
from sqlmodel import Session, SQLModel, create_engine

from app.core.config import settings


def normalize_database_url(database_url: str) -> str:
    """Pin the PostgreSQL driver to psycopg2 while leaving other URLs unchanged."""
    if database_url.startswith("postgresql://"):
        return "postgresql+psycopg2://" + database_url.removeprefix("postgresql://")
    if database_url.startswith("postgres://"):
        return "postgresql+psycopg2://" + database_url.removeprefix("postgres://")
    return database_url


def _engine_kwargs(database_url: str) -> dict[str, object]:
    if database_url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}}
    return {"pool_pre_ping": True}


def create_db_engine(database_url: str | None = None) -> Engine:
    """Build a SQLAlchemy engine for the given URL or the configured database."""
    url = normalize_database_url(database_url or settings.DATABASE_URL)
    return create_engine(url, **_engine_kwargs(url))


engine = create_db_engine()


def get_session() -> Generator[Session, None, None]:
    """Yield a database session for FastAPI route dependencies."""
    with Session(engine) as session:
        yield session


def init_db(bind: Engine | None = None) -> None:
    """Enable pgvector on PostgreSQL and create any missing tables.

    Call this during application startup before serving traffic.
    """
    import app.models  # noqa: F401

    active_engine = engine if bind is None else bind
    if active_engine.dialect.name == "postgresql":
        with active_engine.begin() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    SQLModel.metadata.create_all(active_engine)
