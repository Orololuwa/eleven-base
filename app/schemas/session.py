from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.session import AttackDirection, PauseReason, PlayStructure, SessionType


class SessionCreateIn(BaseModel):
    session_type: SessionType
    play_structure: PlayStructure
    planned_segment_length_minutes: int | None = Field(default=None, ge=1, le=180)
    pitch_id: UUID | None = None

    @model_validator(mode="after")
    def validate_play_structure_rules(self) -> "SessionCreateIn":
        length = self.planned_segment_length_minutes
        if self.play_structure == PlayStructure.halves and length is None:
            raise ValueError(
                "planned_segment_length_minutes is required for halves"
            )
        if self.play_structure == PlayStructure.open and length is not None:
            raise ValueError(
                "planned_segment_length_minutes is unused for open play structure"
            )
        return self


class SessionStartIn(BaseModel):
    attack_direction: AttackDirection | None = None


class SessionSegmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    session_id: UUID
    segment_index: int
    attack_direction: AttackDirection | None
    started_at: datetime
    ended_at: datetime | None


class SessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    session_type: SessionType
    play_structure: PlayStructure
    planned_segment_length_minutes: int | None
    pitch_id: UUID | None
    created_at: datetime
    started_at: datetime | None
    ended_at: datetime | None = None
    segments: list[SessionSegmentOut] = []
    pauses: list["SessionPauseOut"] = []


class SessionPauseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    session_id: UUID
    segment_id: UUID | None
    reason: PauseReason
    started_at: datetime
    ended_at: datetime


class FinalizeSegmentIn(BaseModel):
    segment_index: int = Field(..., ge=1)
    attack_direction: AttackDirection | None = None
    started_at: datetime
    ended_at: datetime


class FinalizePauseIn(BaseModel):
    segment_index: int | None = None
    reason: PauseReason
    started_at: datetime
    ended_at: datetime


class SessionFinalizeIn(BaseModel):
    ended_at: datetime
    segments: list[FinalizeSegmentIn] = []
    pauses: list[FinalizePauseIn] = []


class TrackPointIn(BaseModel):
    sequence_index: int = Field(..., ge=0)
    segment_index: int | None = Field(default=None, ge=1)
    recorded_at: datetime
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)
    speed_kmh: float | None = Field(default=None, ge=0)
    horizontal_accuracy_m: float = Field(..., gt=0)


class TrackPointsIn(BaseModel):
    points: list[TrackPointIn] = Field(..., min_length=1, max_length=1000)

    @model_validator(mode="after")
    def validate_unique_sequence_indices(self) -> "TrackPointsIn":
        indices = [point.sequence_index for point in self.points]
        if len(indices) != len(set(indices)):
            raise ValueError("sequence_index values must be unique within the request")
        return self


class TrackPointsOut(BaseModel):
    inserted: int
    ignored: int
