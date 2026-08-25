from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.session import AttackDirection, PlayStructure, SessionType


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
    segments: list[SessionSegmentOut] = []
