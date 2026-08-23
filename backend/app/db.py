"""SQLite persistence for jobs and tracks (SQLAlchemy 2.x, sync engine)."""

import time
import uuid
from datetime import UTC

from sqlalchemy import Boolean, Float, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


def utcnow() -> float:
    return time.time()


class JobRow(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    playlist_id: Mapped[str] = mapped_column(String(64))
    playlist_name: Mapped[str] = mapped_column(Text, default="")
    playlist_url: Mapped[str] = mapped_column(Text, default="")
    artwork_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="created")
    created_at: Mapped[float] = mapped_column(Float, default=utcnow)
    updated_at: Mapped[float] = mapped_column(Float, default=utcnow, onupdate=utcnow)

    tracks: Mapped[list["TrackRow"]] = relationship(
        back_populates="job", cascade="all, delete-orphan", order_by="TrackRow.position")


class TrackRow(Base):
    __tablename__ = "tracks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id"))
    position: Mapped[int] = mapped_column(Integer)
    spotify_id: Mapped[str] = mapped_column(String(64), default="")
    title: Mapped[str] = mapped_column(Text)
    artists: Mapped[str] = mapped_column(Text, default="")
    album: Mapped[str] = mapped_column(Text, default="")
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    artwork_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    release_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    track_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="queued")
    stage_message: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    source: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    filename: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    bitrate_kbps: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    has_file: Mapped[bool] = mapped_column(Boolean, default=False)

    job: Mapped[JobRow] = relationship(back_populates="tracks")


engine = create_engine(
    f"sqlite:///{settings.data_dir / 'playlist_dl.db'}",
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(engine)


def new_job_id() -> str:
    return uuid.uuid4().hex[:12]
