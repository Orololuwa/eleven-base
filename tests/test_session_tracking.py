import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from geoalchemy2.shape import to_shape
from sqlalchemy.orm import Session

from app.config.database import SessionLocal
from app.models.pitch import Pitch, PitchVisibility, UserSavedPitch
from app.models.session import (
    AttackDirection,
    PauseReason,
    PlaySession,
    PlayStructure,
    SessionPause,
    SessionSegment,
    SessionTrackPoint,
    SessionType,
)
from app.models.user import User
from app.schemas.pitch import PitchCreateIn
from app.schemas.profile import LocationIn
from app.schemas.session import (
    FinalizePauseIn,
    FinalizeSegmentIn,
    SessionCreateIn,
    SessionFinalizeIn,
    SessionStartIn,
    TrackPointIn,
    TrackPointsIn,
)
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
        for point in (
            db.query(SessionTrackPoint)
            .filter(SessionTrackPoint.session_id == session_id)
            .all()
        ):
            db.delete(point)
        for pause in (
            db.query(SessionPause).filter(SessionPause.session_id == session_id).all()
        ):
            db.delete(pause)
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
            for point in (
                db.query(SessionTrackPoint)
                .filter(SessionTrackPoint.session_id == play_session.id)
                .all()
            ):
                db.delete(point)
            for pause in (
                db.query(SessionPause)
                .filter(SessionPause.session_id == play_session.id)
                .all()
            ):
                db.delete(pause)
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
    user = User(email=f"tracking-{uuid.uuid4()}@example.com", email_verified=True)
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
            name="Tracking Pitch",
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


def _start_halves_session(
    db: Session, user: User, cleanup, *, pitch_id: uuid.UUID | None = None
) -> uuid.UUID:
    created = session_service.create_session(
        db,
        user,
        SessionCreateIn(
            session_type=SessionType.match,
            play_structure=PlayStructure.halves,
            planned_segment_length_minutes=45,
            pitch_id=pitch_id,
        ),
    )
    cleanup(session_id=created.id)
    session_service.start_session(
        db,
        user,
        created.id,
        SessionStartIn(
            attack_direction=AttackDirection.end_a if pitch_id is not None else None
        ),
    )
    return created.id


def _start_open_session(db: Session, user: User, cleanup) -> uuid.UUID:
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
    return created.id


def test_finalize_unstarted_session_422(db: Session, cleanup):
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

    with pytest.raises(HTTPException) as exc:
        session_service.finalize_session(
            db,
            user,
            created.id,
            SessionFinalizeIn(
                ended_at=datetime.now(timezone.utc),
                segments=[],
            ),
        )
    assert exc.value.status_code == 422


def test_finalize_other_users_session_404(db: Session, cleanup):
    owner = _make_user(db, cleanup)
    other = _make_user(db, cleanup)
    session_id = _start_open_session(db, owner, cleanup)
    ended_at = datetime.now(timezone.utc)

    with pytest.raises(HTTPException) as exc:
        session_service.finalize_session(
            db,
            other,
            session_id,
            SessionFinalizeIn(ended_at=ended_at),
        )
    assert exc.value.status_code == 404


def test_finalize_open_session_level_pauses(db: Session, cleanup):
    user = _make_user(db, cleanup)
    session_id = _start_open_session(db, user, cleanup)
    started = db.get(PlaySession, session_id)
    assert started is not None
    assert started.started_at is not None

    pause_start = started.started_at + timedelta(minutes=5)
    pause_end = pause_start + timedelta(minutes=2)
    ended_at = started.started_at + timedelta(minutes=30)

    finalized = session_service.finalize_session(
        db,
        user,
        session_id,
        SessionFinalizeIn(
            ended_at=ended_at,
            pauses=[
                FinalizePauseIn(
                    reason=PauseReason.manual,
                    started_at=pause_start,
                    ended_at=pause_end,
                )
            ],
        ),
    )

    assert finalized.ended_at == ended_at
    assert finalized.segments == []
    assert len(finalized.pauses) == 1
    assert finalized.pauses[0].segment_id is None
    assert finalized.pauses[0].reason == PauseReason.manual


def test_finalize_halves_updates_segment_one_and_creates_segment_two(
    db: Session, cleanup
):
    user = _make_user(db, cleanup)
    session_id = _start_halves_session(db, user, cleanup)
    started = db.get(PlaySession, session_id)
    assert started is not None
    assert started.started_at is not None

    segment_one_end = started.started_at + timedelta(minutes=45)
    segment_two_start = segment_one_end
    segment_two_end = segment_two_start + timedelta(minutes=45)
    ended_at = segment_two_end

    finalized = session_service.finalize_session(
        db,
        user,
        session_id,
        SessionFinalizeIn(
            ended_at=ended_at,
            segments=[
                FinalizeSegmentIn(
                    segment_index=1,
                    attack_direction=None,
                    started_at=started.started_at,
                    ended_at=segment_one_end,
                ),
                FinalizeSegmentIn(
                    segment_index=2,
                    attack_direction=None,
                    started_at=segment_two_start,
                    ended_at=segment_two_end,
                ),
            ],
        ),
    )

    assert len(finalized.segments) == 2
    assert finalized.segments[0].segment_index == 1
    assert finalized.segments[0].ended_at == segment_one_end
    assert finalized.segments[1].segment_index == 2
    assert finalized.segments[1].started_at == segment_two_start


def test_finalize_skip_pitch_forces_null_attack_direction(db: Session, cleanup):
    user = _make_user(db, cleanup)
    session_id = _start_halves_session(db, user, cleanup)
    started = db.get(PlaySession, session_id)
    assert started is not None
    assert started.started_at is not None
    ended_at = started.started_at + timedelta(minutes=45)

    with pytest.raises(HTTPException) as exc:
        session_service.finalize_session(
            db,
            user,
            session_id,
            SessionFinalizeIn(
                ended_at=ended_at,
                segments=[
                    FinalizeSegmentIn(
                        segment_index=1,
                        attack_direction=AttackDirection.end_a,
                        started_at=started.started_at,
                        ended_at=ended_at,
                    )
                ],
            ),
        )
    assert exc.value.status_code == 422


def test_finalize_with_pitch_requires_attack_direction(db: Session, cleanup):
    user = _make_user(db, cleanup)
    pitch = _make_pitch(db, user, cleanup)
    session_id = _start_halves_session(db, user, cleanup, pitch_id=pitch.id)
    started = db.get(PlaySession, session_id)
    assert started is not None
    assert started.started_at is not None
    ended_at = started.started_at + timedelta(minutes=45)

    with pytest.raises(HTTPException) as exc:
        session_service.finalize_session(
            db,
            user,
            session_id,
            SessionFinalizeIn(
                ended_at=ended_at,
                segments=[
                    FinalizeSegmentIn(
                        segment_index=1,
                        attack_direction=None,
                        started_at=started.started_at,
                        ended_at=ended_at,
                    )
                ],
            ),
        )
    assert exc.value.status_code == 422

    finalized = session_service.finalize_session(
        db,
        user,
        session_id,
        SessionFinalizeIn(
            ended_at=ended_at,
            segments=[
                FinalizeSegmentIn(
                    segment_index=1,
                    attack_direction=AttackDirection.end_b,
                    started_at=started.started_at,
                    ended_at=ended_at,
                )
            ],
        ),
    )
    assert finalized.segments[0].attack_direction == AttackDirection.end_b


def test_finalize_idempotent_replaces_pauses(db: Session, cleanup):
    user = _make_user(db, cleanup)
    session_id = _start_open_session(db, user, cleanup)
    started = db.get(PlaySession, session_id)
    assert started is not None
    assert started.started_at is not None

    pause_start = started.started_at + timedelta(minutes=1)
    pause_end = pause_start + timedelta(minutes=1)
    ended_at = started.started_at + timedelta(minutes=20)

    first = session_service.finalize_session(
        db,
        user,
        session_id,
        SessionFinalizeIn(
            ended_at=ended_at,
            pauses=[
                FinalizePauseIn(
                    reason=PauseReason.manual,
                    started_at=pause_start,
                    ended_at=pause_end,
                )
            ],
        ),
    )
    assert len(first.pauses) == 1

    second = session_service.finalize_session(
        db,
        user,
        session_id,
        SessionFinalizeIn(
            ended_at=ended_at,
            pauses=[
                FinalizePauseIn(
                    reason=PauseReason.gps_loss,
                    started_at=pause_start,
                    ended_at=pause_end,
                )
            ],
        ),
    )
    assert len(second.pauses) == 1
    assert second.pauses[0].reason == PauseReason.gps_loss
    assert second.pauses[0].id != first.pauses[0].id


def test_track_points_before_finalize_422(db: Session, cleanup):
    user = _make_user(db, cleanup)
    session_id = _start_open_session(db, user, cleanup)

    with pytest.raises(HTTPException) as exc:
        session_service.upload_track_points(
            db,
            user,
            session_id,
            TrackPointsIn(
                points=[
                    TrackPointIn(
                        sequence_index=0,
                        recorded_at=datetime.now(timezone.utc),
                        lat=6.45,
                        lng=3.39,
                        horizontal_accuracy_m=5.0,
                    )
                ]
            ),
        )
    assert exc.value.status_code == 422


def test_track_points_after_finalize_inserts_and_idempotent_retry(
    db: Session, cleanup
):
    user = _make_user(db, cleanup)
    session_id = _start_open_session(db, user, cleanup)
    started = db.get(PlaySession, session_id)
    assert started is not None
    assert started.started_at is not None
    ended_at = started.started_at + timedelta(minutes=30)

    session_service.finalize_session(
        db,
        user,
        session_id,
        SessionFinalizeIn(ended_at=ended_at),
    )

    recorded_at = started.started_at + timedelta(minutes=1)
    payload = TrackPointsIn(
        points=[
            TrackPointIn(
                sequence_index=0,
                recorded_at=recorded_at,
                lat=6.45,
                lng=3.39,
                speed_kmh=10.5,
                horizontal_accuracy_m=8.0,
            )
        ]
    )

    first = session_service.upload_track_points(db, user, session_id, payload)
    assert first.inserted == 1
    assert first.ignored == 0

    second = session_service.upload_track_points(db, user, session_id, payload)
    assert second.inserted == 0
    assert second.ignored == 1

    stored = (
        db.query(SessionTrackPoint)
        .filter(SessionTrackPoint.session_id == session_id)
        .all()
    )
    assert len(stored) == 1
    point = to_shape(stored[0].location)
    assert point.y == pytest.approx(6.45)
    assert point.x == pytest.approx(3.39)


def test_track_points_halves_requires_segment_index(db: Session, cleanup):
    user = _make_user(db, cleanup)
    session_id = _start_halves_session(db, user, cleanup)
    started = db.get(PlaySession, session_id)
    assert started is not None
    assert started.started_at is not None
    ended_at = started.started_at + timedelta(minutes=45)

    session_service.finalize_session(
        db,
        user,
        session_id,
        SessionFinalizeIn(
            ended_at=ended_at,
            segments=[
                FinalizeSegmentIn(
                    segment_index=1,
                    started_at=started.started_at,
                    ended_at=ended_at,
                )
            ],
        ),
    )

    with pytest.raises(HTTPException) as exc:
        session_service.upload_track_points(
            db,
            user,
            session_id,
            TrackPointsIn(
                points=[
                    TrackPointIn(
                        sequence_index=0,
                        recorded_at=started.started_at + timedelta(minutes=1),
                        lat=6.45,
                        lng=3.39,
                        horizontal_accuracy_m=5.0,
                    )
                ]
            ),
        )
    assert exc.value.status_code == 422

    result = session_service.upload_track_points(
        db,
        user,
        session_id,
        TrackPointsIn(
            points=[
                TrackPointIn(
                    sequence_index=0,
                    segment_index=1,
                    recorded_at=started.started_at + timedelta(minutes=1),
                    lat=6.45,
                    lng=3.39,
                    horizontal_accuracy_m=5.0,
                )
            ]
        ),
    )
    assert result.inserted == 1
    stored = (
        db.query(SessionTrackPoint)
        .filter(SessionTrackPoint.session_id == session_id)
        .one()
    )
    assert stored.segment_id is not None
