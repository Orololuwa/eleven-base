import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.config.database import SessionLocal
from app.models.session import (
    IngestFlag,
    PlaySession,
    PlayStructure,
    SegmentMetrics,
    SessionMetrics,
    SessionType,
    SpeedSource,
    SprintEffort,
)
from app.models.user import User
from app.schemas.session import SessionCreateIn, SessionFinalizeIn, SessionStartIn
from app.services import session as session_service

_ZONES = {
    "zone_walk_seconds": 1000,
    "zone_jog_seconds": 500,
    "zone_run_seconds": 300,
    "zone_high_run_seconds": 60,
    "zone_sprint_seconds": 20,
}
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

    db.expire_all()
    for user_id in user_ids:
        for play_session in (
            db.query(PlaySession).filter(PlaySession.user_id == user_id).all()
        ):
            db.delete(play_session)
        user = db.get(User, user_id)
        if user is not None:
            db.delete(user)
    db.commit()


def _make_user(db: Session, cleanup) -> User:
    user = User(email=f"metrics-{uuid.uuid4()}@example.com", email_verified=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    cleanup(user.id)
    return user


def _start_halves_session(db: Session, user: User) -> PlaySession:
    created = session_service.create_session(
        db,
        user,
        SessionCreateIn(
            session_type=SessionType.match,
            play_structure=PlayStructure.halves,
            planned_segment_length_minutes=30,
            extra_time_enabled=False,
        ),
    )
    session_service.start_session(db, user, created.id, SessionStartIn())
    play_session = db.get(PlaySession, created.id)
    assert play_session is not None and play_session.started_at is not None
    return play_session


def _segment_metrics(segment_index: int) -> dict:
    return {
        "segment_index": segment_index,
        "active_duration_seconds": 1900,
        "distance_m": 3000.0,
        "gap_seconds": 20,
        "top_speed_kmh": 25.0,
        "sprint_count": 1,
        "sprint_distance_m": 30.0,
        "calories_kcal": 400,
        **_ZONES,
    }


def _payload(t0: datetime) -> dict:
    """Two 35-minute halves with a 10-minute break and one sprint per half."""
    return {
        "ended_at": t0 + timedelta(minutes=80),
        "segments": [
            {
                "segment_index": 1,
                "started_at": t0,
                "ended_at": t0 + timedelta(minutes=35),
            },
            {
                "segment_index": 2,
                "started_at": t0 + timedelta(minutes=45),
                "ended_at": t0 + timedelta(minutes=80),
            },
        ],
        "metrics": {
            "active_duration_seconds": 3800,
            "distance_m": 6000.0,
            "gap_seconds": 40,
            "top_speed_kmh": 25.0,
            "top_speed_location": {"lat": 6.45, "lng": 3.39},
            "sprint_count": 2,
            "sprint_distance_m": 60.0,
            "calories_kcal": 800,
            **{field: value * 2 for field, value in _ZONES.items()},
            "mass_kg_at_computation": 75.0,
            "speed_source": "os",
            "data_quality": "good",
            "speed_band_bucket": "small",
            "speed_band_boundaries_kmh": dict(_BOUNDARIES),
            "pitch_long_axis_m": 55.0,
            "accepted_fix_count": 3700,
            "algorithm_version": "v1",
            "computed_at": t0 + timedelta(minutes=80),
        },
        "segment_metrics": [_segment_metrics(1), _segment_metrics(2)],
        "sprint_efforts": [
            {
                "effort_index": 0,
                "segment_index": 1,
                "started_at": t0 + timedelta(minutes=5),
                "ended_at": t0 + timedelta(minutes=5, seconds=4),
                "duration_s": 4.0,
                "distance_m": 30.0,
                "peak_speed_kmh": 25.0,
                "peak_location": {"lat": 6.451, "lng": 3.391},
            },
            {
                "effort_index": 1,
                "segment_index": 2,
                "started_at": t0 + timedelta(minutes=50),
                "ended_at": t0 + timedelta(minutes=50, seconds=4),
                "duration_s": 4.0,
                "distance_m": 30.0,
                "peak_speed_kmh": 25.0,
            },
        ],
    }


def _suppress_speed(payload: dict) -> dict:
    for row in [payload["metrics"], *payload["segment_metrics"]]:
        for field in (
            "top_speed_kmh",
            "sprint_count",
            "sprint_distance_m",
            *_ZONES,
        ):
            row[field] = None
    payload["metrics"]["top_speed_location"] = None
    payload["metrics"]["speed_source"] = "none"
    payload["metrics"]["data_quality"] = "estimated"
    payload["sprint_efforts"] = []
    return payload


def _finalize(db: Session, user: User, play_session: PlaySession, payload: dict):
    return session_service.finalize_session(
        db, user, play_session.id, SessionFinalizeIn.model_validate(payload)
    )


# --- Schema validation (no DB) ---


def test_metrics_payload_accepts_valid():
    SessionFinalizeIn.model_validate(_payload(datetime.now(timezone.utc)))


def test_segment_metrics_require_metrics():
    payload = _payload(datetime.now(timezone.utc))
    payload.pop("metrics")
    with pytest.raises(ValidationError):
        SessionFinalizeIn.model_validate(payload)


def test_metrics_require_one_row_per_segment():
    payload = _payload(datetime.now(timezone.utc))
    payload["segment_metrics"] = payload["segment_metrics"][:1]
    with pytest.raises(ValidationError):
        SessionFinalizeIn.model_validate(payload)


def test_sprint_effort_unknown_segment_rejected():
    payload = _payload(datetime.now(timezone.utc))
    payload["sprint_efforts"][0]["segment_index"] = 3
    with pytest.raises(ValidationError):
        SessionFinalizeIn.model_validate(payload)


def test_speed_source_none_rejects_speed_fields():
    payload = _payload(datetime.now(timezone.utc))
    payload["metrics"]["speed_source"] = "none"
    with pytest.raises(ValidationError):
        SessionFinalizeIn.model_validate(payload)


def test_speed_source_os_requires_speed_fields():
    payload = _payload(datetime.now(timezone.utc))
    payload["segment_metrics"][0]["zone_jog_seconds"] = None
    with pytest.raises(ValidationError):
        SessionFinalizeIn.model_validate(payload)


def test_speed_band_boundaries_must_ascend():
    payload = _payload(datetime.now(timezone.utc))
    payload["metrics"]["speed_band_boundaries_kmh"]["jog"] = 5
    with pytest.raises(ValidationError):
        SessionFinalizeIn.model_validate(payload)


# --- Service tests (require migrated DB + PostGIS) ---


def test_finalize_persists_metrics_and_round_trips(db: Session, cleanup):
    user = _make_user(db, cleanup)
    play_session = _start_halves_session(db, user)
    finalized = _finalize(db, user, play_session, _payload(play_session.started_at))

    assert finalized.metrics is not None
    assert finalized.metrics.distance_m == pytest.approx(6000.0)
    assert finalized.metrics.speed_band_boundaries_kmh.sprint == 17
    assert finalized.metrics.top_speed_location is not None
    assert finalized.metrics.top_speed_location.lat == pytest.approx(6.45)
    assert finalized.metrics.ingest_flags == []
    assert [row.segment_index for row in finalized.segment_metrics] == [1, 2]
    assert [e.segment_index for e in finalized.sprint_efforts] == [1, 2]
    assert finalized.sprint_efforts[1].peak_location is None


def test_finalize_without_metrics_still_works(db: Session, cleanup):
    user = _make_user(db, cleanup)
    play_session = _start_halves_session(db, user)
    payload = _payload(play_session.started_at)
    for key in ("metrics", "segment_metrics", "sprint_efforts"):
        payload.pop(key)
    finalized = _finalize(db, user, play_session, payload)
    assert finalized.metrics is None
    assert finalized.segment_metrics == []
    assert finalized.sprint_efforts == []


def test_metrics_first_write_wins(db: Session, cleanup):
    user = _make_user(db, cleanup)
    play_session = _start_halves_session(db, user)
    _finalize(db, user, play_session, _payload(play_session.started_at))

    retry = _payload(play_session.started_at)
    retry["metrics"]["distance_m"] = 9999.0
    retry["metrics"]["algorithm_version"] = "v2"
    finalized = _finalize(db, user, play_session, retry)

    assert finalized.metrics is not None
    assert finalized.metrics.distance_m == pytest.approx(6000.0)
    assert finalized.metrics.algorithm_version == "v1"
    assert (
        db.query(SprintEffort)
        .filter(SprintEffort.session_id == play_session.id)
        .count()
        == 2
    )


def test_unknown_algorithm_version_accepted(db: Session, cleanup):
    user = _make_user(db, cleanup)
    play_session = _start_halves_session(db, user)
    payload = _payload(play_session.started_at)
    payload["metrics"]["algorithm_version"] = "v42-experimental"
    finalized = _finalize(db, user, play_session, payload)
    assert finalized.metrics is not None
    assert finalized.metrics.algorithm_version == "v42-experimental"


def test_speed_source_none_stores_nulls(db: Session, cleanup):
    user = _make_user(db, cleanup)
    play_session = _start_halves_session(db, user)
    payload = _suppress_speed(_payload(play_session.started_at))
    finalized = _finalize(db, user, play_session, payload)

    assert finalized.metrics is not None
    assert finalized.metrics.speed_source == SpeedSource.none
    assert finalized.metrics.top_speed_kmh is None
    assert finalized.metrics.zone_walk_seconds is None
    assert finalized.metrics.calories_kcal == 800
    assert finalized.metrics.ingest_flags == []
    assert finalized.sprint_efforts == []


def _flags_for(db: Session, user: User, payload_edit) -> list[IngestFlag]:
    play_session = _start_halves_session(db, user)
    payload = _payload(play_session.started_at)
    payload_edit(payload)
    finalized = _finalize(db, user, play_session, payload)
    assert finalized.metrics is not None
    return finalized.metrics.ingest_flags


def test_flag_totals_mismatch(db: Session, cleanup):
    user = _make_user(db, cleanup)

    def edit(payload):
        payload["metrics"]["distance_m"] = 6100.0

    assert _flags_for(db, user, edit) == [IngestFlag.totals_mismatch]


def test_float_totals_within_tolerance_not_flagged(db: Session, cleanup):
    user = _make_user(db, cleanup)

    def edit(payload):
        payload["metrics"]["distance_m"] = 6000.4

    assert _flags_for(db, user, edit) == []


def test_flag_duration_incoherent(db: Session, cleanup):
    user = _make_user(db, cleanup)

    def edit(payload):
        payload["segment_metrics"][0]["active_duration_seconds"] = 3000
        payload["segment_metrics"][0]["zone_walk_seconds"] = 2100
        payload["metrics"]["active_duration_seconds"] = 4900
        payload["metrics"]["zone_walk_seconds"] = 3100

    assert _flags_for(db, user, edit) == [IngestFlag.duration_incoherent]


def test_flag_sprint_below_boundary(db: Session, cleanup):
    user = _make_user(db, cleanup)

    def edit(payload):
        payload["sprint_efforts"][0]["peak_speed_kmh"] = 16.0

    assert _flags_for(db, user, edit) == [IngestFlag.sprint_incoherent]


def test_flag_sprint_outside_segment(db: Session, cleanup):
    user = _make_user(db, cleanup)

    def edit(payload):
        t0 = payload["segments"][0]["started_at"]
        payload["sprint_efforts"][0]["started_at"] = t0 + timedelta(minutes=40)
        payload["sprint_efforts"][0]["ended_at"] = t0 + timedelta(
            minutes=40, seconds=4
        )

    assert _flags_for(db, user, edit) == [IngestFlag.sprint_incoherent]


def test_flag_zone_incoherent(db: Session, cleanup):
    user = _make_user(db, cleanup)

    def edit(payload):
        payload["segment_metrics"][0]["zone_walk_seconds"] = 1100
        payload["segment_metrics"][1]["zone_walk_seconds"] = 900

    assert _flags_for(db, user, edit) == [IngestFlag.zone_incoherent]


def test_flag_calorie_implausible(db: Session, cleanup):
    user = _make_user(db, cleanup)

    def edit(payload):
        payload["segment_metrics"][0]["calories_kcal"] = 5000
        payload["metrics"]["calories_kcal"] = 5400

    assert _flags_for(db, user, edit) == [IngestFlag.calorie_implausible]


def test_structural_errors_still_422(db: Session, cleanup):
    user = _make_user(db, cleanup)
    play_session = _start_halves_session(db, user)
    payload = _payload(play_session.started_at)
    payload["segments"][0]["ended_at"] = payload["segments"][1]["ended_at"]
    with pytest.raises(HTTPException) as exc:
        _finalize(db, user, play_session, payload)
    assert exc.value.status_code == 422


def test_deleting_session_cascades_metrics(db: Session, cleanup):
    user = _make_user(db, cleanup)
    play_session = _start_halves_session(db, user)
    finalized = _finalize(db, user, play_session, _payload(play_session.started_at))
    session_id = play_session.id
    segment_ids = [segment.id for segment in finalized.segments]

    db.expire_all()
    db.delete(db.get(PlaySession, session_id))
    db.commit()

    assert (
        db.query(SessionMetrics).filter(SessionMetrics.session_id == session_id).count()
        == 0
    )
    assert (
        db.query(SprintEffort).filter(SprintEffort.session_id == session_id).count()
        == 0
    )
    assert (
        db.query(SegmentMetrics)
        .filter(SegmentMetrics.segment_id.in_(segment_ids))
        .count()
        == 0
    )
