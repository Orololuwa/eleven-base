from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    RootModel,
    model_validator,
)

from app.models.profile import (
    PositionCode,
    PreferredFoot,
    ProfileVisibility,
    SkillLevel,
)


class LocationIn(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)


class LocationOut(BaseModel):
    lat: float
    lng: float


class PositionIn(BaseModel):
    position: PositionCode
    is_preferred: bool = False


class PositionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    position: PositionCode
    is_preferred: bool


class PositionSetIn(
    RootModel[Annotated[list[PositionIn], Field(min_length=1, max_length=5)]]
):
    @model_validator(mode="after")
    def validate_set(self) -> "PositionSetIn":
        positions = self.root
        codes = [p.position for p in positions]
        if len(codes) != len(set(codes)):
            raise ValueError("Duplicate positions are not allowed")
        preferred_count = sum(1 for p in positions if p.is_preferred)
        if preferred_count != 1:
            raise ValueError("Exactly one position must be marked preferred")
        return self

    @property
    def positions(self) -> list[PositionIn]:
        return self.root


class ProfileUpdate(BaseModel):
    display_name: str | None = Field(default=None, max_length=100)
    date_of_birth: date | None = None
    preferred_foot: PreferredFoot | None = None
    height_cm: int | None = Field(default=None, ge=100, le=230)
    skill_level: SkillLevel | None = None
    bio: str | None = Field(default=None, max_length=500)
    location: LocationIn | None = None
    visibility: ProfileVisibility | None = None
    onboarding_completed: bool | None = None


class ProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    display_name: str
    date_of_birth: date | None
    preferred_foot: PreferredFoot | None
    height_cm: int | None
    skill_level: SkillLevel | None
    bio: str | None
    location: LocationOut | None
    visibility: ProfileVisibility
    avatar_public_id: str | None
    avatar_url: str | None
    avatar_updated_at: datetime | None
    onboarding_completed: bool
    positions: list[PositionOut]
    created_at: datetime
    updated_at: datetime


class ProfileReadPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    display_name: str
    preferred_foot: PreferredFoot | None
    height_cm: int | None
    skill_level: SkillLevel | None
    bio: str | None
    avatar_url: str | None
    avatar_updated_at: datetime | None
    positions: list[PositionOut]


class AvatarConfirmIn(BaseModel):
    public_id: str = Field(..., min_length=1)
    secure_url: str = Field(..., min_length=1)


class AvatarSignatureOut(BaseModel):
    signature: str
    timestamp: int
    api_key: str
    cloud_name: str
    folder: str
