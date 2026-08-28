import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from geoalchemy2.elements import WKTElement
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, joinedload

from app.models.session import (
    PlaySession,
    PlayStructure,
    SessionPause,
    SessionSegment,
    SessionTrackPoint,
)
from app.models.user import User
from app.schemas.session import (
    FinalizePauseIn,
    FinalizeSegmentIn,
    SessionCreateIn,
    SessionFinalizeIn,
    SessionPauseOut,
    SessionRead,
    SessionSegmentOut,
    SessionStartIn,
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
        attack_direction=segment.attack_direction,
        started_at=segment.started_at,
        ended_at=segment.ended_at,
    )


def _serialize_session(session: PlaySession) -> SessionRead:
    return SessionRead(
        id=session.id,
        user_id=session.user_id,
        session_type=session.session_type,
        play_structure=session.play_structure,
        planned_segment_length_minutes=session.planned_segment_length_minutes,
        pitch_id=session.pitch_id,
        created_at=session.created_at,
        started_at=session.started_at,
        ended_at=session.ended_at,
        segments=[_serialize_segment(s) for s in session.segments],
        pauses=[_serialize_pause(p) for p in session.pauses],
    )


def _load_session(db: Session, session_id: uuid.UUID) -> PlaySession | None:
    return (
        db.query(PlaySession)
        .options(
            joinedload(PlaySession.segments),
            joinedload(PlaySession.pauses),
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


def _validate_attack_direction(
    play_session: PlaySession,
    attack_direction: object | None,
    label: str,
) -> None:
    if play_session.pitch_id is not None and attack_direction is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{label} attack_direction is required when the session has a pitch",
        )
    if play_session.pitch_id is None and attack_direction is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"{label} attack_direction must be omitted when heatmap was skipped",
        )


def _validate_segments(
    play_session: PlaySession, segments: list[FinalizeSegmentIn]
) -> None:
    if play_session.play_structure == PlayStructure.open:
        if segments:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="segments must be empty for open play structure",
            )
        return

    if not segments:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="segments are required for halves and sets play structures",
        )

    indexes = [segment.segment_index for segment in segments]
    expected = list(range(1, len(segments) + 1))
    if sorted(indexes) != expected:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="segment_index values must be contiguous starting at 1",
        )

    ordered = sorted(segments, key=lambda segment: segment.segment_index)
    for segment in ordered:
        _validate_closed_interval(
            segment.started_at, segment.ended_at, f"segment {segment.segment_index}"
        )
        _validate_attack_direction(
            play_session,
            segment.attack_direction,
            f"segment {segment.segment_index}",
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
    segment_windows: dict[int, tuple[datetime, datetime]] = {
        segment.segment_index: (segment.started_at, segment.ended_at)
        for segment in segments
    }

    grouped: dict[int | None, list[FinalizePauseIn]] = {}
    for pause in pauses:
        _validate_closed_interval(pause.started_at, pause.ended_at, "pause")

        if play_session.play_structure == PlayStructure.open:
            if pause.segment_index is not None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="segment_index must be omitted for open play structure pauses",
                )
            if play_session.started_at is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="session has not started",
                )
            if pause.started_at < play_session.started_at:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="pause started_at must be within the session window",
                )
            if pause.ended_at > session_ended_at:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="pause ended_at must be within the session window",
                )
            grouped.setdefault(None, []).append(pause)
            continue

        if pause.segment_index is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="segment_index is required for halves and sets pauses",
            )
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
            db.add(existing)
        else:
            db.add(
                SessionSegment(
                    session_id=play_session.id,
                    segment_index=segment.segment_index,
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

    if play_session.play_structure != PlayStructure.open:
        if play_session.pitch_id is not None and data.attack_direction is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="attack_direction is required when the session has a pitch",
            )
        if play_session.pitch_id is None and data.attack_direction is not None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="attack_direction must be omitted when heatmap was skipped",
            )

    now = datetime.now(timezone.utc)
    play_session.started_at = now
    db.add(play_session)

    if play_session.play_structure != PlayStructure.open:
        attack = data.attack_direction if play_session.pitch_id is not None else None
        db.add(
            SessionSegment(
                session_id=play_session.id,
                segment_index=1,
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
        segment_id = None
        if pause.segment_index is not None:
            segment_id = segment_ids[pause.segment_index]
        db.add(
            SessionPause(
                session_id=play_session.id,
                segment_id=segment_id,
                reason=pause.reason,
                started_at=pause.started_at,
                ended_at=pause.ended_at,
            )
        )

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
        if play_session.play_structure == PlayStructure.open:
            if point.segment_index is not None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="segment_index must be omitted for open play structure track points",
                )
            segment_id = None
        else:
            if point.segment_index is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="segment_index is required for halves and sets track points",
                )
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
