from datetime import date as CalendarDate
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.session import (
    ActivityKind,
    AttackDirection,
    DataQuality,
    IngestFlag,
    PauseReason,
    PlayStructure,
    SessionType,
    SpeedBandBucket,
    SpeedSource,
)
from app.schemas.profile import LocationIn, LocationOut

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
    title: str | None = None
    segments: list[SessionSegmentOut] = []
    pauses: list["SessionPauseOut"] = []
    metrics: "SessionMetricsOut | None" = None
    segment_metrics: list["SegmentMetricsOut"] = []
    sprint_efforts: list["SprintEffortOut"] = []


class SessionPauseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    session_id: UUID
    segment_id: UUID
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
    segment_index: int = Field(..., ge=1)
    reason: PauseReason
    started_at: datetime
    ended_at: datetime


class SpeedBandBoundaries(BaseModel):
    walk: float = Field(..., gt=0)
    jog: float = Field(..., gt=0)
    run: float = Field(..., gt=0)
    high_run: float = Field(..., gt=0)
    sprint: float = Field(..., gt=0)

    @model_validator(mode="after")
    def validate_ascending(self) -> "SpeedBandBoundaries":
        ordered = [self.walk, self.jog, self.run, self.high_run, self.sprint]
        if any(left > right for left, right in zip(ordered, ordered[1:])):
            raise ValueError("speed band boundaries must be non-decreasing")
        return self


_SPEED_DERIVED_FIELDS = (
    "top_speed_kmh",
    "sprint_count",
    "sprint_distance_m",
    "zone_walk_seconds",
    "zone_jog_seconds",
    "zone_run_seconds",
    "zone_high_run_seconds",
    "zone_sprint_seconds",
)


class _MetricTotalsIn(BaseModel):
    active_duration_seconds: int = Field(..., ge=0)
    distance_m: float = Field(..., ge=0)
    gap_seconds: int = Field(..., ge=0)
    top_speed_kmh: float | None = Field(default=None, ge=0)
    sprint_count: int | None = Field(default=None, ge=0)
    sprint_distance_m: float | None = Field(default=None, ge=0)
    zone_walk_seconds: int | None = Field(default=None, ge=0)
    zone_jog_seconds: int | None = Field(default=None, ge=0)
    zone_run_seconds: int | None = Field(default=None, ge=0)
    zone_high_run_seconds: int | None = Field(default=None, ge=0)
    zone_sprint_seconds: int | None = Field(default=None, ge=0)
    calories_kcal: int = Field(..., ge=0)


class SessionMetricsIn(_MetricTotalsIn):
    top_speed_location: LocationIn | None = None
    mass_kg_at_computation: float = Field(..., gt=0)
    speed_source: SpeedSource
    data_quality: DataQuality
    speed_band_bucket: SpeedBandBucket
    speed_band_boundaries_kmh: SpeedBandBoundaries
    pitch_long_axis_m: float | None = Field(default=None, ge=0)
    accepted_fix_count: int = Field(..., ge=0)
    algorithm_version: str = Field(..., min_length=1, max_length=32)
    computed_at: datetime


class SegmentMetricsIn(_MetricTotalsIn):
    segment_index: int = Field(..., ge=1)


class SprintEffortIn(BaseModel):
    effort_index: int = Field(..., ge=0)
    segment_index: int = Field(..., ge=1)
    started_at: datetime
    ended_at: datetime
    duration_s: float = Field(..., ge=0)
    distance_m: float = Field(..., ge=0)
    peak_speed_kmh: float = Field(..., ge=0)
    peak_location: LocationIn | None = None


class SessionFinalizeIn(BaseModel):
    ended_at: datetime
    segments: list[FinalizeSegmentIn] = []
    pauses: list[FinalizePauseIn] = []
    metrics: SessionMetricsIn | None = None
    segment_metrics: list[SegmentMetricsIn] = []
    sprint_efforts: list[SprintEffortIn] = []

    @model_validator(mode="after")
    def validate_metrics_shape(self) -> "SessionFinalizeIn":
        if self.metrics is None:
            if self.segment_metrics or self.sprint_efforts:
                raise ValueError(
                    "segment_metrics and sprint_efforts require metrics"
                )
            return self

        segment_indexes = {segment.segment_index for segment in self.segments}
        metric_indexes = [row.segment_index for row in self.segment_metrics]
        if len(metric_indexes) != len(set(metric_indexes)):
            raise ValueError("segment_metrics segment_index values must be unique")
        if set(metric_indexes) != segment_indexes:
            raise ValueError("segment_metrics must contain one row per segment")

        effort_indexes = [effort.effort_index for effort in self.sprint_efforts]
        if len(effort_indexes) != len(set(effort_indexes)):
            raise ValueError("sprint_efforts effort_index values must be unique")
        for effort in self.sprint_efforts:
            if effort.segment_index not in segment_indexes:
                raise ValueError(
                    f"sprint effort references unknown segment_index "
                    f"{effort.segment_index}"
                )

        speed_suppressed = self.metrics.speed_source == SpeedSource.none
        for row in [self.metrics, *self.segment_metrics]:
            for field in _SPEED_DERIVED_FIELDS:
                value = getattr(row, field)
                if speed_suppressed and value is not None:
                    raise ValueError(
                        f"{field} must be null when speed_source is none"
                    )
                if not speed_suppressed and value is None:
                    raise ValueError(
                        f"{field} is required unless speed_source is none"
                    )
        if speed_suppressed:
            if self.metrics.top_speed_location is not None:
                raise ValueError(
                    "top_speed_location must be null when speed_source is none"
                )
            if self.sprint_efforts:
                raise ValueError(
                    "sprint_efforts must be empty when speed_source is none"
                )
        return self


class SessionMetricsOut(BaseModel):
    active_duration_seconds: int
    distance_m: float
    gap_seconds: int
    top_speed_kmh: float | None
    top_speed_location: LocationOut | None
    sprint_count: int | None
    sprint_distance_m: float | None
    zone_walk_seconds: int | None
    zone_jog_seconds: int | None
    zone_run_seconds: int | None
    zone_high_run_seconds: int | None
    zone_sprint_seconds: int | None
    calories_kcal: int
    mass_kg_at_computation: float
    speed_source: SpeedSource
    data_quality: DataQuality
    speed_band_bucket: SpeedBandBucket
    speed_band_boundaries_kmh: SpeedBandBoundaries
    pitch_long_axis_m: float | None
    accepted_fix_count: int
    algorithm_version: str
    computed_at: datetime
    ingest_flags: list[IngestFlag]


class SegmentMetricsOut(BaseModel):
    segment_index: int
    active_duration_seconds: int
    distance_m: float
    gap_seconds: int
    top_speed_kmh: float | None
    sprint_count: int | None
    sprint_distance_m: float | None
    zone_walk_seconds: int | None
    zone_jog_seconds: int | None
    zone_run_seconds: int | None
    zone_high_run_seconds: int | None
    zone_sprint_seconds: int | None
    calories_kcal: int


class SprintEffortOut(BaseModel):
    effort_index: int
    segment_index: int
    started_at: datetime
    ended_at: datetime
    duration_s: float
    distance_m: float
    peak_speed_kmh: float
    peak_location: LocationOut | None


class TrackPointIn(BaseModel):
    sequence_index: int = Field(..., ge=0)
    segment_index: int = Field(..., ge=1)
    recorded_at: datetime
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)
    speed_kmh: float | None = Field(default=None, ge=0)
    speed_accuracy_mps: float | None = Field(default=None, ge=0)
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


SESSION_TITLE_MAX_LENGTH = 40


class SessionPitchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str


class SessionListMetrics(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    active_duration_seconds: int
    distance_m: float
    top_speed_kmh: float | None
    speed_source: SpeedSource
    data_quality: DataQuality


class SessionListItem(BaseModel):
    id: UUID
    title: str | None
    session_type: SessionType
    started_at: datetime
    ended_at: datetime
    pitch: SessionPitchOut | None
    metrics: SessionListMetrics | None


class SessionListPage(BaseModel):
    items: list[SessionListItem]
    next_cursor: str | None
    total_count: int | None


class SessionCalendarDay(BaseModel):
    date: CalendarDate
    session_ids: list[UUID]


class SessionCalendar(BaseModel):
    month: str
    days: list[SessionCalendarDay]


class SessionDetail(BaseModel):
    id: UUID
    title: str | None
    session_type: SessionType
    play_structure: PlayStructure
    planned_segment_length_minutes: int | None
    extra_time_enabled: bool | None
    planned_extra_time_segment_length_minutes: int | None
    training_activity_options: list[ActivityKind] | None
    pitch: SessionPitchOut | None
    created_at: datetime
    started_at: datetime | None
    ended_at: datetime | None
    segments: list[SessionSegmentOut]
    metrics: SessionMetricsOut | None
    segment_metrics: list[SegmentMetricsOut]
    sprint_efforts: list[SprintEffortOut]


class SessionTitleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None

    @field_validator("title", mode="before")
    @classmethod
    def normalize_title(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return None
            if len(value) > SESSION_TITLE_MAX_LENGTH:
                raise ValueError(
                    f"title must be at most {SESSION_TITLE_MAX_LENGTH} characters"
                )
        return value


class SessionTitleOut(BaseModel):
    id: UUID
    title: str | None


class WeeklySessionMetrics(BaseModel):
    active_duration_seconds: int
    distance_m: float
    data_quality: DataQuality


class WeeklySessionItem(BaseModel):
    id: UUID
    started_at: datetime
    metrics: WeeklySessionMetrics | None


class WeeklySessionWindow(BaseModel):
    start: datetime
    end: datetime
    items: list[WeeklySessionItem]
