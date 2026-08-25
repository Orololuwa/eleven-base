import uuid

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.config.database import SessionLocal
from app.models.pitch import Pitch, PitchVisibility, UserSavedPitch
from app.models.session import (
    AttackDirection,
    PlaySession,
    PlayStructure,
    SessionSegment,
    SessionType,
)
from app.models.user import User
from app.schemas.pitch import PitchCreateIn
from app.schemas.profile import LocationIn
from app.schemas.session import SessionCreateIn, SessionStartIn
from app.services import pitch as pitch_service
from app.services import session as session_service


@pytest.fixture
def db():
    session: Session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture
def cleanup(db: Session):
    user_ids: list[uuid.UUID] = []
    pitch_ids: list[uuid.UUID] = []
    session_ids: list[uuid.UUID] = []

    def track(
        user_id: uuid.UUID | None = None,
        pitch_id: uuid.UUID | None = None,
        session_id: uuid.UUID | None = None,
    ):
        if user_id is not None:
            user_ids.append(user_id)
        if pitch_id is not None:
            pitch_ids.append(pitch_id)
        if session_id is not None:
            session_ids.append(session_id)

    yield track

    db.expire_all()
    for session_id in session_ids:
        for segment in (
            db.query(SessionSegment)
            .filter(SessionSegment.session_id == session_id)
            .all()
        ):
            db.delete(segment)
        play_session = db.get(PlaySession, session_id)
        if play_session is not None:
            db.delete(play_session)
    for pitch_id in pitch_ids:
        for saved in (
            db.query(UserSavedPitch).filter(UserSavedPitch.pitch_id == pitch_id).all()
        ):
            db.delete(saved)
        pitch = db.get(Pitch, pitch_id)
        if pitch is not None:
            db.delete(pitch)
    for user_id in user_ids:
        for saved in (
            db.query(UserSavedPitch).filter(UserSavedPitch.user_id == user_id).all()
        ):
            db.delete(saved)
        for play_session in (
            db.query(PlaySession).filter(PlaySession.user_id == user_id).all()
        ):
            for segment in (
                db.query(SessionSegment)
                .filter(SessionSegment.session_id == play_session.id)
                .all()
            ):
                db.delete(segment)
            db.delete(play_session)
        user = db.get(User, user_id)
        if user is not None:
            db.delete(user)
    db.commit()


def _make_user(db: Session, cleanup) -> User:
    user = User(email=f"session-{uuid.uuid4()}@example.com", email_verified=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    cleanup(user_id=user.id)
    return user


def _make_pitch(db: Session, user: User, cleanup) -> Pitch:
    created = pitch_service.create_pitch(
        db,
        user,
        PitchCreateIn(
            name="Test Pitch",
            end_a_corner_1=LocationIn(lat=6.45, lng=3.39),
            end_a_corner_2=LocationIn(lat=6.45, lng=3.391),
            end_b_corner_1=LocationIn(lat=6.451, lng=3.39),
            end_b_corner_2=LocationIn(lat=6.451, lng=3.391),
        ),
    )
    cleanup(pitch_id=created.id)
    pitch = db.get(Pitch, created.id)
    assert pitch is not None
    return pitch


# --- Schema validation (no DB) ---


def test_halves_requires_segment_length():
    with pytest.raises(ValidationError):
        SessionCreateIn(
            session_type=SessionType.match,
            play_structure=PlayStructure.halves,
        )


def test_open_rejects_segment_length():
    with pytest.raises(ValidationError):
        SessionCreateIn(
            session_type=SessionType.training,
            play_structure=PlayStructure.open,
            planned_segment_length_minutes=20,
        )


def test_sets_allows_optional_length():
    with_length = SessionCreateIn(
        session_type=SessionType.futsal,
        play_structure=PlayStructure.sets,
        planned_segment_length_minutes=15,
    )
    without = SessionCreateIn(
        session_type=SessionType.futsal,
        play_structure=PlayStructure.sets,
    )
    assert with_length.planned_segment_length_minutes == 15
    assert without.planned_segment_length_minutes is None


def test_halves_accepts_length():
    data = SessionCreateIn(
        session_type=SessionType.match,
        play_structure=PlayStructure.halves,
        planned_segment_length_minutes=45,
    )
    assert data.planned_segment_length_minutes == 45


# --- Service tests (require migrated DB + PostGIS) ---


def test_create_session_pre_kickoff(db: Session, cleanup):
    user = _make_user(db, cleanup)
    created = session_service.create_session(
        db,
        user,
        SessionCreateIn(
            session_type=SessionType.match,
            play_structure=PlayStructure.halves,
            planned_segment_length_minutes=45,
        ),
    )
    cleanup(session_id=created.id)

    assert created.started_at is None
    assert created.pitch_id is None
    assert created.segments == []


def test_create_session_with_pitch_auto_saves(db: Session, cleanup):
    owner = _make_user(db, cleanup)
    user = _make_user(db, cleanup)
    pitch = _make_pitch(db, owner, cleanup)
    pitch.visibility = PitchVisibility.public
    db.add(pitch)
    db.commit()

    created = session_service.create_session(
        db,
        user,
        SessionCreateIn(
            session_type=SessionType.match,
            play_structure=PlayStructure.sets,
            planned_segment_length_minutes=15,
            pitch_id=pitch.id,
        ),
    )
    cleanup(session_id=created.id)

    assert created.pitch_id == pitch.id
    saved_ids = {p.id for p in pitch_service.list_saved(db, user)}
    assert pitch.id in saved_ids


def test_create_session_rejects_invisible_pitch(db: Session, cleanup):
    owner = _make_user(db, cleanup)
    user = _make_user(db, cleanup)
    pitch = _make_pitch(db, owner, cleanup)

    with pytest.raises(HTTPException) as exc:
        session_service.create_session(
            db,
            user,
            SessionCreateIn(
                session_type=SessionType.match,
                play_structure=PlayStructure.open,
                pitch_id=pitch.id,
            ),
        )
    assert exc.value.status_code == 404


def test_start_open_creates_no_segment(db: Session, cleanup):
    user = _make_user(db, cleanup)
    created = session_service.create_session(
        db,
        user,
        SessionCreateIn(
            session_type=SessionType.training,
            play_structure=PlayStructure.open,
        ),
    )
    cleanup(session_id=created.id)

    started = session_service.start_session(
        db, user, created.id, SessionStartIn()
    )
    assert started.started_at is not None
    assert started.segments == []


def test_start_skip_pitch_segment_null_attack(db: Session, cleanup):
    user = _make_user(db, cleanup)
    created = session_service.create_session(
        db,
        user,
        SessionCreateIn(
            session_type=SessionType.match,
            play_structure=PlayStructure.halves,
            planned_segment_length_minutes=45,
        ),
    )
    cleanup(session_id=created.id)

    started = session_service.start_session(
        db, user, created.id, SessionStartIn()
    )
    assert started.started_at is not None
    assert len(started.segments) == 1
    assert started.segments[0].segment_index == 1
    assert started.segments[0].attack_direction is None
    assert started.segments[0].started_at == started.started_at


def test_start_with_pitch_requires_attack_direction(db: Session, cleanup):
    user = _make_user(db, cleanup)
    pitch = _make_pitch(db, user, cleanup)
    created = session_service.create_session(
        db,
        user,
        SessionCreateIn(
            session_type=SessionType.match,
            play_structure=PlayStructure.halves,
            planned_segment_length_minutes=45,
            pitch_id=pitch.id,
        ),
    )
    cleanup(session_id=created.id)

    with pytest.raises(HTTPException) as exc:
        session_service.start_session(db, user, created.id, SessionStartIn())
    assert exc.value.status_code == 422

    started = session_service.start_session(
        db,
        user,
        created.id,
        SessionStartIn(attack_direction=AttackDirection.end_a),
    )
    assert len(started.segments) == 1
    assert started.segments[0].attack_direction == AttackDirection.end_a


def test_double_start_conflict(db: Session, cleanup):
    user = _make_user(db, cleanup)
    created = session_service.create_session(
        db,
        user,
        SessionCreateIn(
            session_type=SessionType.training,
            play_structure=PlayStructure.open,
        ),
    )
    cleanup(session_id=created.id)

    session_service.start_session(db, user, created.id, SessionStartIn())
    with pytest.raises(HTTPException) as exc:
        session_service.start_session(db, user, created.id, SessionStartIn())
    assert exc.value.status_code == 409


def test_start_other_users_session_404(db: Session, cleanup):
    owner = _make_user(db, cleanup)
    other = _make_user(db, cleanup)
    created = session_service.create_session(
        db,
        owner,
        SessionCreateIn(
            session_type=SessionType.training,
            play_structure=PlayStructure.open,
        ),
    )
    cleanup(session_id=created.id)

    with pytest.raises(HTTPException) as exc:
        session_service.start_session(db, other, created.id, SessionStartIn())
    assert exc.value.status_code == 404
