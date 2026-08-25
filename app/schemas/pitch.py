from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.pitch import PitchVisibility
from app.schemas.profile import LocationIn, LocationOut


class PitchCornersIn(BaseModel):
    end_a_corner_1: LocationIn
    end_a_corner_2: LocationIn
    end_b_corner_1: LocationIn
    end_b_corner_2: LocationIn


class PitchCreateIn(PitchCornersIn):
    name: str = Field(..., min_length=1, max_length=200)


class PitchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    created_by_user_id: UUID | None
    visibility: PitchVisibility
    verified: bool
    end_a_corner_1: LocationOut
    end_a_corner_2: LocationOut
    end_b_corner_1: LocationOut
    end_b_corner_2: LocationOut
    created_at: datetime


class PitchNearbyOut(PitchRead):
    distance_meters: float
