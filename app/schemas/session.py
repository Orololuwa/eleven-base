from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.session import (
    ActivityKind,
    AttackDirection,
    PauseReason,
    PlayStructure,
    SessionType,
)

_SESSION_TYPE_PLAY_STRUCTURES: dict[SessionType, set[PlayStructure]] = {
    SessionType.match: {PlayStructure.halves},
    SessionType.futsal: {PlayStructure.halves, PlayStructure.sets},
    SessionType.training: {PlayStructure.training_activities},
}


class SessionCreateIn(BaseModel):
    session_type: SessionType
    play_structure: PlayStructure
    planned_segment_length_minutes: int | None = Field(default=None, ge=1, le=180)
    extra_time_enabled: bool | None = None
    planned_extra_time_segment_length_minutes: int | None = Field(
        default=None, ge=1, le=180
    )
    training_activity_options: list[ActivityKind] | None = None
    pitch_id: UUID | None = None

    @model_validator(mode="after")
    def validate_play_structure_rules(self) -> "SessionCreateIn":
        allowed = _SESSION_TYPE_PLAY_STRUCTURES[self.session_type]
        if self.play_structure not in allowed:
            allowed_values = ", ".join(sorted(s.value for s in allowed))
            raise ValueError(
                f"play_structure must be one of [{allowed_values}] "
                f"for session_type {self.session_type.value}"
            )

        length = self.planned_segment_length_minutes
        if self.play_structure == PlayStructure.halves and length is None:
            raise ValueError(
                "planned_segment_length_minutes is required for halves"
            )
        if (
            self.play_structure == PlayStructure.training_activities
            and length is not None
        ):
            raise ValueError(
                "planned_segment_length_minutes is unused for training_activities"
            )

        if self.play_structure == PlayStructure.halves:
            if self.extra_time_enabled is None:
                raise ValueError(
                    "extra_time_enabled is required for halves play structure"
                )
        elif self.extra_time_enabled:
            raise ValueError(
                "extra_time_enabled must be false or omitted when play_structure "
                "is not halves"
            )

        if self.extra_time_enabled is True:
            if self.planned_extra_time_segment_length_minutes is None:
                raise ValueError(
                    "planned_extra_time_segment_length_minutes is required "
                    "when extra_time_enabled is true"
                )
        elif self.planned_extra_time_segment_length_minutes is not None:
            raise ValueError(
                "planned_extra_time_segment_length_minutes must be omitted "
                "when extra_time_enabled is not true"
            )

        if self.session_type == SessionType.training:
            options = self.training_activity_options
            if not options:
                raise ValueError(
                    "training_activity_options is required for training sessions"
                )
            if len(options) != len(set(options)):
                raise ValueError("training_activity_options must be unique")
        elif self.training_activity_options is not None:
            raise ValueError(
                "training_activity_options is only allowed for training sessions"
            )

        if self.pitch_id is not None:
            if self.session_type == SessionType.training:
                options = self.training_activity_options or []
                if ActivityKind.set not in options:
                    raise ValueError(
                        "pitch_id is only allowed for training when "
                        "training_activity_options includes set"
                    )

        return self


class SessionStartIn(BaseModel):
    attack_direction: AttackDirection | None = None
    activity_kind: ActivityKind | None = None


class SessionSegmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    session_id: UUID
    segment_index: int
    activity_kind: ActivityKind | None = None
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
    extra_time_enabled: bool | None = None
    planned_extra_time_segment_length_minutes: int | None = None
    training_activity_options: list[ActivityKind] | None = None
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
    activity_kind: ActivityKind | None = None
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
