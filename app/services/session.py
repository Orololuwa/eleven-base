import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from geoalchemy2.elements import WKTElement
from sqlalchemy.dialects.postgresql import insert
from geoalchemy2.shape import to_shape
from sqlalchemy.orm import Session, joinedload, selectinload

from app.models.session import (
    ActivityKind,
    IngestFlag,
    PlaySession,
    PlayStructure,
    SegmentMetrics,
    SessionMetrics,
    SessionPause,
    SessionSegment,
    SessionTrackPoint,
    SessionType,
    SpeedSource,
    SprintEffort,
)
from app.models.user import User
from app.schemas.profile import LocationIn, LocationOut
from app.schemas.session import (
    FinalizePauseIn,
    FinalizeSegmentIn,
    SegmentMetricsOut,
    SessionCreateIn,
    SessionFinalizeIn,
    SessionMetricsOut,
    SessionPauseOut,
    SessionRead,
    SessionSegmentOut,
    SessionStartIn,
    SprintEffortOut,
    TrackPointsIn,
    TrackPointsOut,
)
from app.services import pitch as pitch_service


def _serialize_pause(pause: SessionPause) -> SessionPauseOut:
    return SessionPauseOut(
        id=pause.id,
        session_id=pause.session_id,
        segment_id=pause.segment_id,
        reason=pause.reason,
        started_at=pause.started_at,
        ended_at=pause.ended_at,
    )


def _serialize_segment(segment: SessionSegment) -> SessionSegmentOut:
    return SessionSegmentOut(
        id=segment.id,
        session_id=segment.session_id,
        segment_index=segment.segment_index,
        activity_kind=segment.activity_kind,
        attack_direction=segment.attack_direction,
        started_at=segment.started_at,
        ended_at=segment.ended_at,
    )


def _location_to_out(location) -> LocationOut | None:
    if location is None:
        return None
    point = to_shape(location)
    return LocationOut(lat=point.y, lng=point.x)


def _location_to_wkt(location: LocationIn | None) -> WKTElement | None:
    if location is None:
        return None
    return WKTElement(f"POINT({location.lng} {location.lat})", srid=4326)


def _serialize_session_metrics(metrics: SessionMetrics) -> SessionMetricsOut:
    return SessionMetricsOut(
        active_duration_seconds=metrics.active_duration_seconds,
        distance_m=metrics.distance_m,
        gap_seconds=metrics.gap_seconds,
        top_speed_kmh=metrics.top_speed_kmh,
        top_speed_location=_location_to_out(metrics.top_speed_location),
        sprint_count=metrics.sprint_count,
        sprint_distance_m=metrics.sprint_distance_m,
        zone_walk_seconds=metrics.zone_walk_seconds,
        zone_jog_seconds=metrics.zone_jog_seconds,
        zone_run_seconds=metrics.zone_run_seconds,
        zone_high_run_seconds=metrics.zone_high_run_seconds,
        zone_sprint_seconds=metrics.zone_sprint_seconds,
        calories_kcal=metrics.calories_kcal,
        mass_kg_at_computation=metrics.mass_kg_at_computation,
        speed_source=metrics.speed_source,
        data_quality=metrics.data_quality,
        speed_band_bucket=metrics.speed_band_bucket,
        speed_band_boundaries_kmh=metrics.speed_band_boundaries_kmh,
        pitch_long_axis_m=metrics.pitch_long_axis_m,
        accepted_fix_count=metrics.accepted_fix_count,
        algorithm_version=metrics.algorithm_version,
        computed_at=metrics.computed_at,
        ingest_flags=list(metrics.ingest_flags or []),
    )


def _serialize_segment_metrics(
    segment: SessionSegment, metrics: SegmentMetrics
) -> SegmentMetricsOut:
    return SegmentMetricsOut(
        segment_index=segment.segment_index,
        active_duration_seconds=metrics.active_duration_seconds,
        distance_m=metrics.distance_m,
        gap_seconds=metrics.gap_seconds,
        top_speed_kmh=metrics.top_speed_kmh,
        sprint_count=metrics.sprint_count,
        sprint_distance_m=metrics.sprint_distance_m,
        zone_walk_seconds=metrics.zone_walk_seconds,
        zone_jog_seconds=metrics.zone_jog_seconds,
        zone_run_seconds=metrics.zone_run_seconds,
        zone_high_run_seconds=metrics.zone_high_run_seconds,
        zone_sprint_seconds=metrics.zone_sprint_seconds,
        calories_kcal=metrics.calories_kcal,
    )


def _serialize_sprint_effort(
    effort: SprintEffort, segment_indexes: dict[uuid.UUID, int]
) -> SprintEffortOut:
    return SprintEffortOut(
        effort_index=effort.effort_index,
        segment_index=segment_indexes[effort.segment_id],
        started_at=effort.started_at,
        ended_at=effort.ended_at,
        duration_s=effort.duration_s,
        distance_m=effort.distance_m,
        peak_speed_kmh=effort.peak_speed_kmh,
        peak_location=_location_to_out(effort.peak_location),
    )


def _serialize_session(session: PlaySession) -> SessionRead:
    segment_indexes = {s.id: s.segment_index for s in session.segments}
    return SessionRead(
        id=session.id,
        user_id=session.user_id,
        session_type=session.session_type,
        play_structure=session.play_structure,
        planned_segment_length_minutes=session.planned_segment_length_minutes,
        extra_time_enabled=session.extra_time_enabled,
        planned_extra_time_segment_length_minutes=(
            session.planned_extra_time_segment_length_minutes
        ),
        training_activity_options=session.training_activity_options,
        pitch_id=session.pitch_id,
        created_at=session.created_at,
        started_at=session.started_at,
        ended_at=session.ended_at,
        segments=[_serialize_segment(s) for s in session.segments],
        pauses=[_serialize_pause(p) for p in session.pauses],
        metrics=(
            _serialize_session_metrics(session.metrics)
            if session.metrics is not None
            else None
        ),
        segment_metrics=[
            _serialize_segment_metrics(s, s.metrics)
            for s in session.segments
            if s.metrics is not None
        ],
        sprint_efforts=[
            _serialize_sprint_effort(e, segment_indexes)
            for e in session.sprint_efforts
        ],
    )


def _load_session(db: Session, session_id: uuid.UUID) -> PlaySession | None:
    return (
        db.query(PlaySession)
        .options(
            joinedload(PlaySession.segments).selectinload(SessionSegment.metrics),
            joinedload(PlaySession.pauses),
            selectinload(PlaySession.metrics),
            selectinload(PlaySession.sprint_efforts),
        )
        .filter(PlaySession.id == session_id)
        .one_or_none()
    )


def _require_owned_session(
    db: Session, user: User, session_id: uuid.UUID
) -> PlaySession:
    play_session = _load_session(db, session_id)
    if play_session is None or play_session.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )
    return play_session


def _validate_closed_interval(
    started_at: datetime, ended_at: datetime, label: str
) -> None:
    if ended_at <= started_at:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{label} ended_at must be after started_at",
        )


def _attack_direction_required(
    play_session: PlaySession, activity_kind: ActivityKind | None
) -> bool:
    if play_session.pitch_id is None:
        return False
    if play_session.session_type == SessionType.training:
        return activity_kind == ActivityKind.set
    return True


def _validate_attack_direction(
    play_session: PlaySession,
    attack_direction: object | None,
    label: str,
    activity_kind: ActivityKind | None = None,
) -> None:
    required = _attack_direction_required(play_session, activity_kind)
    if required and attack_direction is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{label} attack_direction is required when the session has a pitch",
        )
    if not required and attack_direction is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                f"{label} attack_direction must be omitted when heatmap was skipped "
                "or the segment does not use attack direction"
            ),
        )


def _training_options(play_session: PlaySession) -> set[ActivityKind]:
    options = play_session.training_activity_options or []
    return {
        ActivityKind(option) if not isinstance(option, ActivityKind) else option
        for option in options
    }


def _validate_segments(
    play_session: PlaySession, segments: list[FinalizeSegmentIn]
) -> None:
    if not segments:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="segments are required",
        )

    indexes = [segment.segment_index for segment in segments]
    expected = list(range(1, len(segments) + 1))
    if sorted(indexes) != expected:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="segment_index values must be contiguous starting at 1",
        )

    if play_session.play_structure == PlayStructure.halves:
        max_segments = 4 if play_session.extra_time_enabled else 2
        if len(segments) > max_segments:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"halves sessions allow at most {max_segments} segments "
                    f"(extra_time_enabled={play_session.extra_time_enabled})"
                ),
            )

    allowed_kinds = _training_options(play_session)
    ordered = sorted(segments, key=lambda segment: segment.segment_index)
    for segment in ordered:
        _validate_closed_interval(
            segment.started_at, segment.ended_at, f"segment {segment.segment_index}"
        )

        if play_session.play_structure == PlayStructure.training_activities:
            if segment.activity_kind is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        f"segment {segment.segment_index} activity_kind is required "
                        "for training_activities"
                    ),
                )
            if segment.activity_kind not in allowed_kinds:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        f"segment {segment.segment_index} activity_kind must be one of "
                        "the session's training_activity_options"
                    ),
                )
        elif segment.activity_kind is not None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"segment {segment.segment_index} activity_kind must be omitted "
                    "for match and futsal sessions"
                ),
            )

        _validate_attack_direction(
            play_session,
            segment.attack_direction,
            f"segment {segment.segment_index}",
            activity_kind=segment.activity_kind,
        )

    for left, right in zip(ordered, ordered[1:]):
        if left.ended_at > right.started_at:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"segment {left.segment_index} ended_at must be on or before "
                    f"segment {right.segment_index} started_at"
                ),
            )


def _validate_pauses(
    play_session: PlaySession,
    segments: list[FinalizeSegmentIn],
    pauses: list[FinalizePauseIn],
    session_ended_at: datetime,
) -> None:
    _ = (play_session, session_ended_at)
    segment_windows: dict[int, tuple[datetime, datetime]] = {
        segment.segment_index: (segment.started_at, segment.ended_at)
        for segment in segments
    }

    grouped: dict[int, list[FinalizePauseIn]] = {}
    for pause in pauses:
        _validate_closed_interval(pause.started_at, pause.ended_at, "pause")

        window = segment_windows.get(pause.segment_index)
        if window is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"pause references unknown segment_index {pause.segment_index}",
            )
        segment_started_at, segment_ended_at = window
        if pause.started_at < segment_started_at or pause.ended_at > segment_ended_at:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"pause for segment {pause.segment_index} must be within "
                    "that segment's window"
                ),
            )
        grouped.setdefault(pause.segment_index, []).append(pause)

    for group in grouped.values():
        ordered = sorted(group, key=lambda pause: pause.started_at)
        for left, right in zip(ordered, ordered[1:]):
            if left.ended_at > right.started_at:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="pauses must not overlap within the same scope",
                )


def _upsert_segments(
    db: Session,
    play_session: PlaySession,
    segments: list[FinalizeSegmentIn],
) -> dict[int, uuid.UUID]:
    existing_by_index = {
        segment.segment_index: segment for segment in play_session.segments
    }
    payload_indexes = {segment.segment_index for segment in segments}

    for segment in segments:
        existing = existing_by_index.get(segment.segment_index)
        if existing is not None:
            existing.started_at = segment.started_at
            existing.ended_at = segment.ended_at
            existing.attack_direction = segment.attack_direction
            existing.activity_kind = segment.activity_kind
            db.add(existing)
        else:
            db.add(
                SessionSegment(
                    session_id=play_session.id,
                    segment_index=segment.segment_index,
                    activity_kind=segment.activity_kind,
                    attack_direction=segment.attack_direction,
                    started_at=segment.started_at,
                    ended_at=segment.ended_at,
                )
            )

    for segment in list(play_session.segments):
        if segment.segment_index not in payload_indexes:
            db.delete(segment)

    db.flush()

    refreshed = (
        db.query(SessionSegment)
        .filter(SessionSegment.session_id == play_session.id)
        .all()
    )
    return {segment.segment_index: segment.id for segment in refreshed}


_SUMMED_INT_FIELDS = (
    "active_duration_seconds",
    "gap_seconds",
    "calories_kcal",
    "sprint_count",
    "zone_walk_seconds",
    "zone_jog_seconds",
    "zone_run_seconds",
    "zone_high_run_seconds",
    "zone_sprint_seconds",
)
_SUMMED_FLOAT_FIELDS = ("distance_m", "sprint_distance_m")
_ZONE_FIELDS = (
    "zone_walk_seconds",
    "zone_jog_seconds",
    "zone_run_seconds",
    "zone_high_run_seconds",
    "zone_sprint_seconds",
)
_FLOAT_TOTAL_TOLERANCE = 0.5
_DURATION_TOLERANCE_SECONDS = 1
_ZONE_TOLERANCE_SECONDS = 5
_MAX_MET = 19.0
_CALORIE_CEILING_SLACK = 1.1


def _totals_match(data: SessionFinalizeIn) -> bool:
    metrics = data.metrics
    assert metrics is not None
    for field in (*_SUMMED_INT_FIELDS, *_SUMMED_FLOAT_FIELDS):
        total = getattr(metrics, field)
        parts = [getattr(row, field) for row in data.segment_metrics]
        if total is None or any(part is None for part in parts):
            if total is not None or any(part is not None for part in parts):
                return False
            continue
        if field in _SUMMED_FLOAT_FIELDS:
            if abs(total - sum(parts)) > _FLOAT_TOTAL_TOLERANCE:
                return False
        elif total != sum(parts):
            return False
    return True


def _durations_coherent(data: SessionFinalizeIn) -> bool:
    metrics = data.metrics
    assert metrics is not None
    if metrics.gap_seconds > metrics.active_duration_seconds:
        return False
    windows = {s.segment_index: s for s in data.segments}
    for row in data.segment_metrics:
        segment = windows[row.segment_index]
        span = (segment.ended_at - segment.started_at).total_seconds()
        if row.active_duration_seconds > span + _DURATION_TOLERANCE_SECONDS:
            return False
        if row.gap_seconds > row.active_duration_seconds:
            return False
    return True


def _sprints_coherent(data: SessionFinalizeIn) -> bool:
    metrics = data.metrics
    assert metrics is not None
    boundary = metrics.speed_band_boundaries_kmh.sprint
    windows = {s.segment_index: s for s in data.segments}

    for effort in data.sprint_efforts:
        segment = windows[effort.segment_index]
        if effort.ended_at < effort.started_at:
            return False
        if effort.started_at < segment.started_at or effort.ended_at > segment.ended_at:
            return False
        if effort.peak_speed_kmh < boundary:
            return False

    ordered = sorted(data.sprint_efforts, key=lambda effort: effort.started_at)
    for left, right in zip(ordered, ordered[1:]):
        if left.ended_at > right.started_at:
            return False

    if metrics.sprint_count is not None:
        if metrics.sprint_count != len(data.sprint_efforts):
            return False
        for row in data.segment_metrics:
            in_segment = sum(
                1 for e in data.sprint_efforts if e.segment_index == row.segment_index
            )
            if row.sprint_count != in_segment:
                return False
    return True


def _zones_coherent(data: SessionFinalizeIn) -> bool:
    metrics = data.metrics
    assert metrics is not None
    if metrics.speed_source == SpeedSource.none:
        return True
    for row in data.segment_metrics:
        zone_total = sum(getattr(row, field) for field in _ZONE_FIELDS)
        covered = row.active_duration_seconds - row.gap_seconds
        if abs(zone_total - covered) > _ZONE_TOLERANCE_SECONDS:
            return False
    return True


def _calories_plausible(data: SessionFinalizeIn) -> bool:
    metrics = data.metrics
    assert metrics is not None
    ceiling = (
        _CALORIE_CEILING_SLACK
        * _MAX_MET
        * 3.5
        / 200
        * metrics.mass_kg_at_computation
        * (metrics.active_duration_seconds / 60)
    )
    return 0 <= metrics.calories_kcal <= ceiling


def _compute_ingest_flags(data: SessionFinalizeIn) -> list[IngestFlag]:
    flags: list[IngestFlag] = []
    if not _totals_match(data):
        flags.append(IngestFlag.totals_mismatch)
    if not _durations_coherent(data):
        flags.append(IngestFlag.duration_incoherent)
    if not _sprints_coherent(data):
        flags.append(IngestFlag.sprint_incoherent)
    if not _zones_coherent(data):
        flags.append(IngestFlag.zone_incoherent)
    if not _calories_plausible(data):
        flags.append(IngestFlag.calorie_implausible)
    return flags


def _insert_metrics(
    db: Session,
    play_session: PlaySession,
    data: SessionFinalizeIn,
    segment_ids: dict[int, uuid.UUID],
) -> None:
    metrics = data.metrics
    assert metrics is not None
    stmt = (
        insert(SessionMetrics)
        .values(
            session_id=play_session.id,
            **metrics.model_dump(
                exclude={"top_speed_location", "speed_band_boundaries_kmh"}
            ),
            top_speed_location=_location_to_wkt(metrics.top_speed_location),
            speed_band_boundaries_kmh=metrics.speed_band_boundaries_kmh.model_dump(),
            ingest_flags=[flag.value for flag in _compute_ingest_flags(data)],
        )
        .on_conflict_do_nothing(index_elements=[SessionMetrics.session_id])
        .returning(SessionMetrics.id)
    )
    if db.execute(stmt).first() is None:
        return

    for row in data.segment_metrics:
        db.add(
            SegmentMetrics(
                segment_id=segment_ids[row.segment_index],
                **row.model_dump(exclude={"segment_index"}),
            )
        )
    for effort in data.sprint_efforts:
        db.add(
            SprintEffort(
                session_id=play_session.id,
                segment_id=segment_ids[effort.segment_index],
                **effort.model_dump(exclude={"segment_index", "peak_location"}),
                peak_location=_location_to_wkt(effort.peak_location),
            )
        )


def create_session(db: Session, user: User, data: SessionCreateIn) -> SessionRead:
    pitch_id = data.pitch_id
    if pitch_id is not None:
        pitch = pitch_service.get_visible_pitch(db, pitch_id, user)
        pitch_service.ensure_saved(db, user, pitch)

    play_session = PlaySession(
        user_id=user.id,
        session_type=data.session_type,
        play_structure=data.play_structure,
        planned_segment_length_minutes=data.planned_segment_length_minutes,
        extra_time_enabled=data.extra_time_enabled,
        planned_extra_time_segment_length_minutes=(
            data.planned_extra_time_segment_length_minutes
        ),
        training_activity_options=(
            [kind.value for kind in data.training_activity_options]
            if data.training_activity_options is not None
            else None
        ),
        pitch_id=pitch_id,
    )
    db.add(play_session)
    db.commit()
    loaded = _load_session(db, play_session.id)
    assert loaded is not None
    return _serialize_session(loaded)


def start_session(
    db: Session,
    user: User,
    session_id: uuid.UUID,
    data: SessionStartIn,
) -> SessionRead:
    play_session = _load_session(db, session_id)
    if play_session is None or play_session.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found",
        )
    if play_session.started_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Session already started",
        )

    activity_kind: ActivityKind | None = None
    if play_session.play_structure == PlayStructure.training_activities:
        if data.activity_kind is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="activity_kind is required for training_activities",
            )
        if data.activity_kind not in _training_options(play_session):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="activity_kind must be one of the session's training_activity_options",
            )
        activity_kind = data.activity_kind
    elif data.activity_kind is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="activity_kind must be omitted for match and futsal sessions",
        )

    _validate_attack_direction(
        play_session,
        data.attack_direction,
        "start",
        activity_kind=activity_kind,
    )

    now = datetime.now(timezone.utc)
    play_session.started_at = now
    db.add(play_session)

    attack = (
        data.attack_direction
        if _attack_direction_required(play_session, activity_kind)
        else None
    )
    db.add(
        SessionSegment(
            session_id=play_session.id,
            segment_index=1,
            activity_kind=activity_kind,
            attack_direction=attack,
            started_at=now,
        )
    )

    db.commit()
    loaded = _load_session(db, play_session.id)
    assert loaded is not None
    return _serialize_session(loaded)


def finalize_session(
    db: Session,
    user: User,
    session_id: uuid.UUID,
    data: SessionFinalizeIn,
) -> SessionRead:
    play_session = _require_owned_session(db, user, session_id)

    if play_session.started_at is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="session has not started",
        )
    if data.ended_at < play_session.started_at:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="ended_at must be on or after session started_at",
        )

    _validate_segments(play_session, data.segments)
    _validate_pauses(play_session, data.segments, data.pauses, data.ended_at)

    _upsert_segments(db, play_session, data.segments)

    db.query(SessionPause).filter(SessionPause.session_id == play_session.id).delete()

    segment_ids = {
        segment.segment_index: segment.id
        for segment in db.query(SessionSegment)
        .filter(SessionSegment.session_id == play_session.id)
        .all()
    }

    for pause in data.pauses:
        db.add(
            SessionPause(
                session_id=play_session.id,
                segment_id=segment_ids[pause.segment_index],
                reason=pause.reason,
                started_at=pause.started_at,
                ended_at=pause.ended_at,
            )
        )

    if data.metrics is not None:
        _insert_metrics(db, play_session, data, segment_ids)

    play_session.ended_at = data.ended_at
    db.add(play_session)
    db.commit()

    loaded = _load_session(db, play_session.id)
    assert loaded is not None
    return _serialize_session(loaded)


def upload_track_points(
    db: Session,
    user: User,
    session_id: uuid.UUID,
    data: TrackPointsIn,
) -> TrackPointsOut:
    play_session = _require_owned_session(db, user, session_id)

    if play_session.ended_at is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="session must be finalized before uploading track points",
        )

    segment_ids = {
        segment.segment_index: segment.id for segment in play_session.segments
    }

    rows: list[dict] = []
    for point in data.points:
        segment_id = segment_ids.get(point.segment_index)
        if segment_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"track point references unknown segment_index {point.segment_index}",
            )

        rows.append(
            {
                "session_id": play_session.id,
                "segment_id": segment_id,
                "sequence_index": point.sequence_index,
                "recorded_at": point.recorded_at,
                "location": WKTElement(
                    f"POINT({point.lng} {point.lat})", srid=4326
                ),
                "speed_kmh": point.speed_kmh,
                "speed_accuracy_mps": point.speed_accuracy_mps,
                "horizontal_accuracy_m": point.horizontal_accuracy_m,
            }
        )

    stmt = (
        insert(SessionTrackPoint)
        .values(rows)
        .on_conflict_do_nothing(constraint="uq_session_track_points_session_sequence")
        .returning(SessionTrackPoint.id)
    )
    inserted_ids = db.execute(stmt).fetchall()
    inserted = len(inserted_ids)
    ignored = len(data.points) - inserted
    db.commit()

    return TrackPointsOut(inserted=inserted, ignored=ignored)
