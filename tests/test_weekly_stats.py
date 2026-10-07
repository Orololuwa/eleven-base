import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.config.database import SessionLocal
from app.models.session import (
    DataQuality,
    PlaySession,
    PlayStructure,
    SessionMetrics,
    SessionType,
    SpeedBandBucket,
    SpeedSource,
)
from app.models.user import User
from app.services import session as session_service

_BOUNDARIES = {"walk": 7, "jog": 10, "run": 14, "high_run": 17, "sprint": 17}


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

    yield user_ids.append

    db.rollback()
    db.expire_all()
    for user_id in user_ids:
        db.query(PlaySession).filter(PlaySession.user_id == user_id).delete(
            synchronize_session=False
        )
        user = db.get(User, user_id)
        if user is not None:
            db.delete(user)
    db.commit()


def _make_user(db: Session, cleanup) -> User:
    user = User(email=f"weekly-{uuid.uuid4()}@example.com", email_verified=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    cleanup(user.id)
    return user


def _add_session(
    db: Session,
    user: User,
    started_at: datetime | None,
    *,
    ended: bool = True,
    with_metrics: bool = False,
    data_quality: DataQuality = DataQuality.good,
) -> PlaySession:
    play_session = PlaySession(
        user_id=user.id,
        session_type=SessionType.match,
        play_structure=PlayStructure.halves,
        planned_segment_length_minutes=30,
        extra_time_enabled=False,
        started_at=started_at,
        ended_at=(
            started_at + timedelta(minutes=60)
            if ended and started_at is not None
            else (datetime.now(timezone.utc) if ended else None)
        ),
    )
    db.add(play_session)
    db.flush()
    if with_metrics:
        db.add(
            SessionMetrics(
                session_id=play_session.id,
                active_duration_seconds=3600,
                distance_m=6000.0,
                top_speed_kmh=25.0,
                calories_kcal=700,
                mass_kg_at_computation=75.0,
                speed_source=SpeedSource.os,
                data_quality=data_quality,
                speed_band_bucket=SpeedBandBucket.full,
                speed_band_boundaries_kmh=dict(_BOUNDARIES),
                accepted_fix_count=3600,
                gap_seconds=0,
                algorithm_version="v1",
                computed_at=play_session.ended_at or datetime.now(timezone.utc),
                ingest_flags=[],
            )
        )
    db.commit()
    db.refresh(play_session)
    return play_session


def test_weekly_window_is_an_ended_range_with_metrics(db: Session, cleanup):
    user = _make_user(db, cleanup)
    other = _make_user(db, cleanup)
    start = datetime(2026, 10, 5, 0, 0, tzinfo=timezone.utc)
    end = start + timedelta(days=14)

    at_start = _add_session(db, user, start, with_metrics=True)
    inside = _add_session(
        db,
        user,
        start + timedelta(days=2, hours=18),
        with_metrics=True,
        data_quality=DataQuality.estimated,
    )
    insufficient = _add_session(
        db,
        user,
        start + timedelta(days=3),
        with_metrics=True,
        data_quality=DataQuality.insufficient,
    )
    no_metrics = _add_session(db, user, start + timedelta(days=4))
    same_instant_low = _add_session(db, user, start + timedelta(days=1))
    same_instant_high = _add_session(db, user, start + timedelta(days=1))
    _add_session(db, user, start - timedelta(minutes=1), with_metrics=True)
    _add_session(db, user, end, with_metrics=True)
    _add_session(db, user, start + timedelta(days=1), ended=False, with_metrics=True)
    _add_session(db, other, start + timedelta(days=1), with_metrics=True)

    window = session_service.get_weekly_window(db, user, start, end)

    tie_ids = sorted(
        (same_instant_low.id, same_instant_high.id), reverse=True
    )
    assert [item.id for item in window.items] == [
        no_metrics.id,
        insufficient.id,
        inside.id,
        *tie_ids,
        at_start.id,
    ]
    assert window.start == start
    assert window.end == end

    by_id = {item.id: item for item in window.items}
    assert by_id[at_start.id].metrics is not None
    assert by_id[at_start.id].metrics.distance_m == 6000.0
    assert by_id[at_start.id].metrics.active_duration_seconds == 3600
    assert by_id[at_start.id].metrics.data_quality == DataQuality.good
    assert by_id[inside.id].metrics.data_quality == DataQuality.estimated
    assert by_id[insufficient.id].metrics.data_quality == DataQuality.insufficient
    assert by_id[no_metrics.id].metrics is None
    assert set(by_id[at_start.id].metrics.model_dump()) == {
        "active_duration_seconds",
        "distance_m",
        "data_quality",
    }


def test_weekly_rejects_naive_bounds(db: Session, cleanup):
    user = _make_user(db, cleanup)
    start = datetime(2026, 10, 5, 0, 0)
    end = start + timedelta(days=7)
    with pytest.raises(HTTPException) as exc:
        session_service.get_weekly_window(db, user, start, end)
    assert exc.value.status_code == 422


def test_weekly_rejects_start_not_before_end(db: Session, cleanup):
    user = _make_user(db, cleanup)
    start = datetime(2026, 10, 5, tzinfo=timezone.utc)
    with pytest.raises(HTTPException) as exc:
        session_service.get_weekly_window(db, user, start, start)
    assert exc.value.status_code == 422


def test_weekly_rejects_span_over_15_days(db: Session, cleanup):
    user = _make_user(db, cleanup)
    start = datetime(2026, 10, 5, tzinfo=timezone.utc)
    end = start + timedelta(days=15, seconds=1)
    with pytest.raises(HTTPException) as exc:
        session_service.get_weekly_window(db, user, start, end)
    assert exc.value.status_code == 422


def test_weekly_accepts_span_of_15_days(db: Session, cleanup):
    user = _make_user(db, cleanup)
    start = datetime(2026, 10, 5, tzinfo=timezone.utc)
    end = start + timedelta(days=15)
    window = session_service.get_weekly_window(db, user, start, end)
    assert window.items == []
