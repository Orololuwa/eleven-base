import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from geoalchemy2 import Geography
from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
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
    training_activities = "training_activities"


class ActivityKind(str, enum.Enum):
    run = "run"
    drill = "drill"
    set = "set"


class AttackDirection(str, enum.Enum):
    end_a = "end_a"
    end_b = "end_b"


class PauseReason(str, enum.Enum):
    manual = "manual"
    gps_loss = "gps_loss"
    backgrounded = "backgrounded"


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
    play_structure: Mapped[PlayStructure] = mapped_column(String(32), nullable=False)
    planned_segment_length_minutes: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    extra_time_enabled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    planned_extra_time_segment_length_minutes: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    training_activity_options: Mapped[list[ActivityKind] | None] = mapped_column(
        ARRAY(String(16)), nullable=True
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
    ended_at: Mapped[datetime | None] = mapped_column(
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
    pauses: Mapped[list["SessionPause"]] = relationship(
        "SessionPause",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="SessionPause.started_at",
    )
    track_points: Mapped[list["SessionTrackPoint"]] = relationship(
        "SessionTrackPoint",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="SessionTrackPoint.sequence_index",
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
    activity_kind: Mapped[ActivityKind | None] = mapped_column(
        String(16), nullable=True
    )
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
    pauses: Mapped[list["SessionPause"]] = relationship(
        "SessionPause",
        back_populates="segment",
        cascade="all, delete-orphan",
        order_by="SessionPause.started_at",
    )
    track_points: Mapped[list["SessionTrackPoint"]] = relationship(
        "SessionTrackPoint",
        back_populates="segment",
        cascade="all, delete-orphan",
        order_by="SessionTrackPoint.sequence_index",
    )


class SessionPause(Base):
    __tablename__ = "session_pauses"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    segment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("session_segments.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    reason: Mapped[PauseReason] = mapped_column(String(16), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    ended_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    session: Mapped["PlaySession"] = relationship(
        "PlaySession", back_populates="pauses"
    )
    segment: Mapped["SessionSegment | None"] = relationship(
        "SessionSegment", back_populates="pauses"
    )


class SessionTrackPoint(Base):
    __tablename__ = "session_track_points"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "sequence_index",
            name="uq_session_track_points_session_sequence",
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
    segment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("session_segments.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    sequence_index: Mapped[int] = mapped_column(Integer, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    location = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=False),
        nullable=False,
    )
    speed_kmh: Mapped[float | None] = mapped_column(Float, nullable=True)
    horizontal_accuracy_m: Mapped[float] = mapped_column(Float, nullable=False)

    session: Mapped["PlaySession"] = relationship(
        "PlaySession", back_populates="track_points"
    )
    segment: Mapped["SessionSegment | None"] = relationship(
        "SessionSegment", back_populates="track_points"
    )
