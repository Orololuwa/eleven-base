import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config.database import Base

if TYPE_CHECKING:
    from app.models.pitch import Pitch
    from app.models.user import User


class SessionType(str, enum.Enum):
    match = "match"
    training = "training"
    futsal = "futsal"


class PlayStructure(str, enum.Enum):
    halves = "halves"
    sets = "sets"
    open = "open"


class AttackDirection(str, enum.Enum):
    end_a = "end_a"
    end_b = "end_b"


class PlaySession(Base):
    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    session_type: Mapped[SessionType] = mapped_column(String(16), nullable=False)
    play_structure: Mapped[PlayStructure] = mapped_column(String(16), nullable=False)
    planned_segment_length_minutes: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    pitch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pitches.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user: Mapped["User"] = relationship("User", back_populates="play_sessions")
    pitch: Mapped["Pitch | None"] = relationship("Pitch", back_populates="sessions")
    segments: Mapped[list["SessionSegment"]] = relationship(
        "SessionSegment",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="SessionSegment.segment_index",
    )


class SessionSegment(Base):
    __tablename__ = "session_segments"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "segment_index",
            name="uq_session_segments_session_index",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    segment_index: Mapped[int] = mapped_column(Integer, nullable=False)
    attack_direction: Mapped[AttackDirection | None] = mapped_column(
        String(16), nullable=True
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    session: Mapped["PlaySession"] = relationship(
        "PlaySession", back_populates="segments"
    )
