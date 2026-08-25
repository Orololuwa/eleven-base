import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session, joinedload

from app.models.session import PlaySession, PlayStructure, SessionSegment
from app.models.user import User
from app.schemas.session import (
    SessionCreateIn,
    SessionRead,
    SessionSegmentOut,
    SessionStartIn,
)
from app.services import pitch as pitch_service


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
        segments=[_serialize_segment(s) for s in session.segments],
    )


def _load_session(db: Session, session_id: uuid.UUID) -> PlaySession | None:
    return (
        db.query(PlaySession)
        .options(joinedload(PlaySession.segments))
        .filter(PlaySession.id == session_id)
        .one_or_none()
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
