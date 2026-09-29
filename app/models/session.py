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
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
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


class SpeedSource(str, enum.Enum):
    os = "os"
    position_delta = "position_delta"
    none = "none"


class DataQuality(str, enum.Enum):
    good = "good"
    estimated = "estimated"
    insufficient = "insufficient"


class SpeedBandBucket(str, enum.Enum):
    futsal = "futsal"
    small = "small"
    mid = "mid"
    full = "full"


class IngestFlag(str, enum.Enum):
    totals_mismatch = "totals_mismatch"
    duration_incoherent = "duration_incoherent"
    sprint_incoherent = "sprint_incoherent"
    zone_incoherent = "zone_incoherent"
    calorie_implausible = "calorie_implausible"


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
    metrics: Mapped["SessionMetrics | None"] = relationship(
        "SessionMetrics",
        back_populates="session",
        cascade="all, delete-orphan",
        uselist=False,
    )
    sprint_efforts: Mapped[list["SprintEffort"]] = relationship(
        "SprintEffort",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="SprintEffort.effort_index",
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
    metrics: Mapped["SegmentMetrics | None"] = relationship(
        "SegmentMetrics",
        back_populates="segment",
        cascade="all, delete-orphan",
        uselist=False,
    )
    sprint_efforts: Mapped[list["SprintEffort"]] = relationship(
        "SprintEffort",
        back_populates="segment",
        cascade="all, delete-orphan",
        order_by="SprintEffort.effort_index",
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
    segment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("session_segments.id", ondelete="CASCADE"),
        nullable=False,
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
    segment: Mapped["SessionSegment"] = relationship(
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
    segment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("session_segments.id", ondelete="CASCADE"),
        nullable=False,
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
    speed_accuracy_mps: Mapped[float | None] = mapped_column(Float, nullable=True)
    horizontal_accuracy_m: Mapped[float] = mapped_column(Float, nullable=False)

    session: Mapped["PlaySession"] = relationship(
        "PlaySession", back_populates="track_points"
    )
    segment: Mapped["SessionSegment"] = relationship(
        "SessionSegment", back_populates="track_points"
    )


class SessionMetrics(Base):
    __tablename__ = "session_metrics"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    active_duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    distance_m: Mapped[float] = mapped_column(Float, nullable=False)
    top_speed_kmh: Mapped[float | None] = mapped_column(Float, nullable=True)
    top_speed_location = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=False),
        nullable=True,
    )
    sprint_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sprint_distance_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    zone_walk_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    zone_jog_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    zone_run_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    zone_high_run_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    zone_sprint_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    calories_kcal: Mapped[int] = mapped_column(Integer, nullable=False)
    mass_kg_at_computation: Mapped[float] = mapped_column(Float, nullable=False)
    speed_source: Mapped[SpeedSource] = mapped_column(String(16), nullable=False)
    data_quality: Mapped[DataQuality] = mapped_column(String(16), nullable=False)
    speed_band_bucket: Mapped[SpeedBandBucket] = mapped_column(
        String(16), nullable=False
    )
    speed_band_boundaries_kmh: Mapped[dict] = mapped_column(JSONB, nullable=False)
    pitch_long_axis_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    accepted_fix_count: Mapped[int] = mapped_column(Integer, nullable=False)
    gap_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    algorithm_version: Mapped[str] = mapped_column(String(32), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    ingest_flags: Mapped[list[IngestFlag]] = mapped_column(
        ARRAY(String(32)), nullable=False, default=list
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    session: Mapped["PlaySession"] = relationship(
        "PlaySession", back_populates="metrics"
    )


class SegmentMetrics(Base):
    __tablename__ = "segment_metrics"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    segment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("session_segments.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    active_duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    distance_m: Mapped[float] = mapped_column(Float, nullable=False)
    gap_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    top_speed_kmh: Mapped[float | None] = mapped_column(Float, nullable=True)
    sprint_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sprint_distance_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    zone_walk_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    zone_jog_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    zone_run_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    zone_high_run_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    zone_sprint_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    calories_kcal: Mapped[int] = mapped_column(Integer, nullable=False)

    segment: Mapped["SessionSegment"] = relationship(
        "SessionSegment", back_populates="metrics"
    )


class SprintEffort(Base):
    __tablename__ = "sprint_efforts"
    __table_args__ = (
        UniqueConstraint(
            "session_id",
            "effort_index",
            name="uq_sprint_efforts_session_effort_index",
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
    segment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("session_segments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    effort_index: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    ended_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    duration_s: Mapped[float] = mapped_column(Float, nullable=False)
    distance_m: Mapped[float] = mapped_column(Float, nullable=False)
    peak_speed_kmh: Mapped[float] = mapped_column(Float, nullable=False)
    peak_location = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=False),
        nullable=True,
    )

    session: Mapped["PlaySession"] = relationship(
        "PlaySession", back_populates="sprint_efforts"
    )
    segment: Mapped["SessionSegment"] = relationship(
        "SessionSegment", back_populates="sprint_efforts"
    )
