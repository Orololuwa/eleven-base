import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from geoalchemy2 import Geography
from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config.database import Base

if TYPE_CHECKING:
    from app.models.session import PlaySession
    from app.models.user import User


class PitchVisibility(str, enum.Enum):
    private = "private"
    public = "public"


class Pitch(Base):
    __tablename__ = "pitches"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    visibility: Mapped[PitchVisibility] = mapped_column(
        String(16), nullable=False, default=PitchVisibility.private
    )
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    end_a_corner_1 = mapped_column(
        Geography(geometry_type="POINT", srid=4326), nullable=False
    )
    end_a_corner_2 = mapped_column(
        Geography(geometry_type="POINT", srid=4326), nullable=False
    )
    end_b_corner_1 = mapped_column(
        Geography(geometry_type="POINT", srid=4326), nullable=False
    )
    end_b_corner_2 = mapped_column(
        Geography(geometry_type="POINT", srid=4326), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    created_by: Mapped["User | None"] = relationship(
        "User", back_populates="created_pitches"
    )
    saved_by: Mapped[list["UserSavedPitch"]] = relationship(
        "UserSavedPitch",
        back_populates="pitch",
        cascade="all, delete-orphan",
    )
    sessions: Mapped[list["PlaySession"]] = relationship(
        "PlaySession", back_populates="pitch"
    )


class UserSavedPitch(Base):
    __tablename__ = "user_saved_pitches"
    __table_args__ = (
        UniqueConstraint("user_id", "pitch_id", name="uq_user_saved_pitches_user_pitch"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    pitch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("pitches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    saved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship("User", back_populates="saved_pitches")
    pitch: Mapped["Pitch"] = relationship("Pitch", back_populates="saved_by")
