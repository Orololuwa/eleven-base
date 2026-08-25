import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.config.database import Base

if TYPE_CHECKING:
    from app.models.identity import UserIdentity
    from app.models.pitch import Pitch, UserSavedPitch
    from app.models.profile import PlayerProfile
    from app.models.session import PlaySession


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    identities: Mapped[list["UserIdentity"]] = relationship(
        "UserIdentity", back_populates="user", cascade="all, delete-orphan"
    )
    profile: Mapped["PlayerProfile | None"] = relationship(
        "PlayerProfile",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )
    created_pitches: Mapped[list["Pitch"]] = relationship(
        "Pitch", back_populates="created_by"
    )
    saved_pitches: Mapped[list["UserSavedPitch"]] = relationship(
        "UserSavedPitch",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    play_sessions: Mapped[list["PlaySession"]] = relationship(
        "PlaySession",
        back_populates="user",
        cascade="all, delete-orphan",
    )
