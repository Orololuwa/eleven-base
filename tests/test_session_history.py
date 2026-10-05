import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.config.database import SessionLocal
from app.models.session import (
    DataQuality,
    PlaySession,
    PlayStructure,
    SessionMetrics,
    SessionPause,
    SessionSegment,
    SessionType,
    SpeedBandBucket,
    SpeedSource,
)
from app.models.user import User
from app.schemas.session import SessionTitleUpdate
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
    user = User(email=f"history-{uuid.uuid4()}@example.com", email_verified=True)
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
    session_type: SessionType = SessionType.match,
    with_metrics: bool = False,
) -> PlaySession:
    structure = (
        PlayStructure.training_activities
        if session_type == SessionType.training
        else PlayStructure.halves
    )
    play_session = PlaySession(
        user_id=user.id,
        session_type=session_type,
        play_structure=structure,
        planned_segment_length_minutes=(
            None if structure == PlayStructure.training_activities else 30
        ),
        extra_time_enabled=(
            None if structure == PlayStructure.training_activities else False
        ),
        training_activity_options=(
            ["run"] if session_type == SessionType.training else None
        ),
        started_at=started_at,
        ended_at=(
            started_at + timedelta(minutes=60)
            if ended and started_at is not None
            else None
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
                data_quality=DataQuality.good,
                speed_band_bucket=SpeedBandBucket.full,
                speed_band_boundaries_kmh=dict(_BOUNDARIES),
                accepted_fix_count=3600,
                gap_seconds=0,
                algorithm_version="v1",
                computed_at=play_session.ended_at,
                ingest_flags=[],
            )
        )
    db.commit()
    db.refresh(play_session)
    return play_session


# --- Title schema (no DB) ---


def test_title_is_trimmed():
    assert SessionTitleUpdate(title="  Cup final  ").title == "Cup final"


@pytest.mark.parametrize("value", ["", "   ", None])
def test_blank_title_clears_override(value):
    assert SessionTitleUpdate(title=value).title is None


def test_title_over_40_characters_rejected():
    with pytest.raises(ValidationError):
        SessionTitleUpdate(title="x" * 41)


def test_title_update_forbids_other_fields():
    with pytest.raises(ValidationError):
        SessionTitleUpdate.model_validate({"title": "a", "session_type": "training"})


# --- List ---


def test_list_returns_only_ended_sessions(db: Session, cleanup):
    user = _make_user(db, cleanup)
    now = datetime.now(timezone.utc)
    ended = _add_session(db, user, now - timedelta(days=1))
    _add_session(db, user, None, ended=False)
    _add_session(db, user, now - timedelta(hours=1), ended=False)

    page = session_service.list_history(db, user, None, None, 20)

    assert [item.id for item in page.items] == [ended.id]
    assert page.total_count == 1
    assert page.next_cursor is None


def test_list_left_joins_metrics(db: Session, cleanup):
    user = _make_user(db, cleanup)
    now = datetime.now(timezone.utc)
    with_metrics = _add_session(db, user, now - timedelta(days=1), with_metrics=True)
    without_metrics = _add_session(db, user, now - timedelta(days=2))

    page = session_service.list_history(db, user, None, None, 20)
    by_id = {item.id: item for item in page.items}

    assert by_id[with_metrics.id].metrics is not None
    assert by_id[with_metrics.id].metrics.distance_m == 6000.0
    assert by_id[without_metrics.id].metrics is None


def test_list_keyset_pages_newest_first(db: Session, cleanup):
    user = _make_user(db, cleanup)
    now = datetime.now(timezone.utc)
    sessions = [_add_session(db, user, now - timedelta(days=i)) for i in range(5)]

    first = session_service.list_history(db, user, None, None, 2)
    second = session_service.list_history(db, user, None, first.next_cursor, 2)
    third = session_service.list_history(db, user, None, second.next_cursor, 2)

    assert first.total_count == 5
    assert second.total_count is None
    assert third.next_cursor is None
    ids = [item.id for page in (first, second, third) for item in page.items]
    assert ids == [s.id for s in sessions]


def test_list_filters_by_type(db: Session, cleanup):
    user = _make_user(db, cleanup)
    now = datetime.now(timezone.utc)
    _add_session(db, user, now - timedelta(days=1))
    futsal = _add_session(
        db, user, now - timedelta(days=2), session_type=SessionType.futsal
    )

    page = session_service.list_history(db, user, SessionType.futsal, None, 20)

    assert [item.id for item in page.items] == [futsal.id]
    assert page.total_count == 1


def test_list_rejects_bad_cursor(db: Session, cleanup):
    user = _make_user(db, cleanup)
    with pytest.raises(HTTPException) as exc:
        session_service.list_history(db, user, None, "not-a-cursor", 20)
    assert exc.value.status_code == 422


# --- Calendar ---


def test_calendar_buckets_by_local_date(db: Session, cleanup):
    user = _make_user(db, cleanup)
    late_utc = datetime(2026, 9, 3, 23, 30, tzinfo=timezone.utc)
    play_session = _add_session(db, user, late_utc)

    utc = session_service.get_history_calendar(db, user, "2026-09", "UTC", None)
    lagos = session_service.get_history_calendar(
        db, user, "2026-09", "Africa/Lagos", None
    )

    assert [(d.date.isoformat(), d.session_ids) for d in utc.days] == [
        ("2026-09-03", [play_session.id])
    ]
    assert [(d.date.isoformat(), d.session_ids) for d in lagos.days] == [
        ("2026-09-04", [play_session.id])
    ]


def test_calendar_rejects_unknown_timezone(db: Session, cleanup):
    user = _make_user(db, cleanup)
    with pytest.raises(HTTPException) as exc:
        session_service.get_history_calendar(db, user, "2026-09", "Mars/Base", None)
    assert exc.value.status_code == 422


def test_calendar_rejects_bad_month(db: Session, cleanup):
    user = _make_user(db, cleanup)
    with pytest.raises(HTTPException) as exc:
        session_service.get_history_calendar(db, user, "2026-13", "UTC", None)
    assert exc.value.status_code == 422


# --- Detail ---


def test_detail_omits_pauses_and_handles_missing_metrics(db: Session, cleanup):
    user = _make_user(db, cleanup)
    started_at = datetime.now(timezone.utc) - timedelta(days=1)
    play_session = _add_session(db, user, started_at)
    segment = SessionSegment(
        session_id=play_session.id,
        segment_index=1,
        started_at=started_at,
        ended_at=started_at + timedelta(minutes=30),
    )
    db.add(segment)
    db.flush()
    db.add(
        SessionPause(
            session_id=play_session.id,
            segment_id=segment.id,
            reason="manual",
            started_at=started_at + timedelta(minutes=5),
            ended_at=started_at + timedelta(minutes=6),
        )
    )
    db.commit()

    detail = session_service.get_session_detail(db, user, play_session.id)

    assert not hasattr(detail, "pauses")
    assert [s.segment_index for s in detail.segments] == [1]
    assert detail.metrics is None
    assert detail.segment_metrics == []
    assert detail.sprint_efforts == []


def test_detail_hides_other_users_session(db: Session, cleanup):
    owner = _make_user(db, cleanup)
    other = _make_user(db, cleanup)
    play_session = _add_session(db, owner, datetime.now(timezone.utc))

    with pytest.raises(HTTPException) as exc:
        session_service.get_session_detail(db, other, play_session.id)
    assert exc.value.status_code == 404


# --- Rename ---


def test_rename_sets_and_clears_title(db: Session, cleanup):
    user = _make_user(db, cleanup)
    play_session = _add_session(db, user, None, ended=False)

    renamed = session_service.rename_session(
        db, user, play_session.id, SessionTitleUpdate(title="  Cup final ")
    )
    assert renamed.title == "Cup final"

    cleared = session_service.rename_session(
        db, user, play_session.id, SessionTitleUpdate(title="   ")
    )
    assert cleared.title is None


def test_rename_missing_session_is_404(db: Session, cleanup):
    user = _make_user(db, cleanup)
    with pytest.raises(HTTPException) as exc:
        session_service.rename_session(
            db, user, uuid.uuid4(), SessionTitleUpdate(title="x")
        )
    assert exc.value.status_code == 404


# --- Delete ---


def test_delete_removes_session_and_children(db: Session, cleanup):
    user = _make_user(db, cleanup)
    play_session = _add_session(
        db, user, datetime.now(timezone.utc), with_metrics=True
    )
    session_id = play_session.id

    session_service.delete_session(db, user, session_id)

    db.expire_all()
    assert db.get(PlaySession, session_id) is None
    assert (
        db.query(SessionMetrics).filter(SessionMetrics.session_id == session_id).count()
        == 0
    )


def test_delete_other_users_session_is_404(db: Session, cleanup):
    owner = _make_user(db, cleanup)
    other = _make_user(db, cleanup)
    play_session = _add_session(db, owner, datetime.now(timezone.utc))

    with pytest.raises(HTTPException) as exc:
        session_service.delete_session(db, other, play_session.id)
    assert exc.value.status_code == 404
    db.expire_all()
    assert db.get(PlaySession, play_session.id) is not None
