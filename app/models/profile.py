import enum
import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from geoalchemy2 import Geography
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config.database import Base

if TYPE_CHECKING:
    from app.models.user import User


class PreferredFoot(str, enum.Enum):
    left = "left"
    right = "right"
    both = "both"


class SkillLevel(str, enum.Enum):
    beginner = "beginner"
    intermediate = "intermediate"
    advanced = "advanced"
    pro = "pro"


class ProfileVisibility(str, enum.Enum):
    public = "public"
    private = "private"


class PositionCode(str, enum.Enum):
    GK = "GK"
    CB = "CB"
    LB = "LB"
    RB = "RB"
    LWB = "LWB"
    RWB = "RWB"
    CDM = "CDM"
    CM = "CM"
    CAM = "CAM"
    LM = "LM"
    RM = "RM"
    LW = "LW"
    RW = "RW"
    SS = "SS"
    ST = "ST"


class PlayerProfile(Base):
    __tablename__ = "player_profiles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    display_name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    preferred_foot: Mapped[PreferredFoot | None] = mapped_column(
        String(16), nullable=True
    )
    height_cm: Mapped[int | None] = mapped_column(Integer, nullable=True)
    skill_level: Mapped[SkillLevel | None] = mapped_column(String(32), nullable=True)
    bio: Mapped[str | None] = mapped_column(Text, nullable=True)
    location = mapped_column(
        Geography(geometry_type="POINT", srid=4326), nullable=True
    )
    visibility: Mapped[ProfileVisibility] = mapped_column(
        String(16), nullable=False, default=ProfileVisibility.public
    )
    avatar_public_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    avatar_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    onboarding_completed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    user: Mapped["User"] = relationship("User", back_populates="profile")
    positions: Mapped[list["PlayerPosition"]] = relationship(
        "PlayerPosition",
        back_populates="player_profile",
        cascade="all, delete-orphan",
        order_by="PlayerPosition.created_at",
    )


class PlayerPosition(Base):
    __tablename__ = "player_positions"
    __table_args__ = (
        UniqueConstraint(
            "player_profile_id",
            "position",
            name="uq_player_positions_profile_position",
        ),
        Index(
            "one_preferred_per_player",
            "player_profile_id",
            unique=True,
            postgresql_where=text("is_preferred = true"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    player_profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("player_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[PositionCode] = mapped_column(String(8), nullable=False)
    is_preferred: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    player_profile: Mapped["PlayerProfile"] = relationship(
        "PlayerProfile", back_populates="positions"
    )
