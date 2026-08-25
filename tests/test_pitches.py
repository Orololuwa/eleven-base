import uuid

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.config.database import SessionLocal
from app.models.pitch import Pitch, PitchVisibility, UserSavedPitch
from app.models.user import User
from app.schemas.pitch import PitchCornersIn, PitchCreateIn
from app.schemas.profile import LocationIn
from app.services import pitch as pitch_service


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

    def track(user_id: uuid.UUID | None = None, pitch_id: uuid.UUID | None = None):
        if user_id is not None:
            user_ids.append(user_id)
        if pitch_id is not None:
            pitch_ids.append(pitch_id)

    yield track

    db.expire_all()
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
        user = db.get(User, user_id)
        if user is not None:
            db.delete(user)
    db.commit()


def _make_user(db: Session, cleanup) -> User:
    user = User(email=f"pitch-{uuid.uuid4()}@example.com", email_verified=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    cleanup(user_id=user.id)
    return user


def _corners(
    base_lat: float = 6.4500,
    base_lng: float = 3.3900,
    span: float = 0.001,
) -> PitchCornersIn:
    return PitchCornersIn(
        end_a_corner_1=LocationIn(lat=base_lat, lng=base_lng),
        end_a_corner_2=LocationIn(lat=base_lat, lng=base_lng + span),
        end_b_corner_1=LocationIn(lat=base_lat + span, lng=base_lng),
        end_b_corner_2=LocationIn(lat=base_lat + span, lng=base_lng + span),
    )


def _create_in(
    name: str = "Lekki Astro",
    base_lat: float = 6.4500,
    base_lng: float = 3.3900,
) -> PitchCreateIn:
    corners = _corners(base_lat=base_lat, base_lng=base_lng)
    return PitchCreateIn(name=name, **corners.model_dump())


# --- Schema validation (no DB) ---


def test_pitch_create_rejects_empty_name():
    with pytest.raises(ValidationError):
        PitchCreateIn(name="", **_corners().model_dump())


def test_pitch_corners_reject_bad_lat():
    with pytest.raises(ValidationError):
        LocationIn(lat=100, lng=0)


# --- Service tests (require migrated DB + PostGIS) ---


def test_create_pitch_auto_saves(db: Session, cleanup):
    user = _make_user(db, cleanup)
    created = pitch_service.create_pitch(db, user, _create_in())
    cleanup(pitch_id=created.id)

    assert created.name == "Lekki Astro"
    assert created.visibility == PitchVisibility.private
    assert created.created_by_user_id == user.id
    assert created.end_a_corner_1.lat == pytest.approx(6.4500)

    saved = pitch_service.list_saved(db, user)
    assert len(saved) == 1
    assert saved[0].id == created.id


def test_unsave_does_not_delete_pitch(db: Session, cleanup):
    user = _make_user(db, cleanup)
    created = pitch_service.create_pitch(db, user, _create_in())
    cleanup(pitch_id=created.id)

    pitch_service.unsave_pitch(db, user, created.id)
    assert pitch_service.list_saved(db, user) == []

    pitch = db.get(Pitch, created.id)
    assert pitch is not None
    assert pitch.name == "Lekki Astro"


def test_nearby_excludes_others_private_pitches(db: Session, cleanup):
    owner = _make_user(db, cleanup)
    viewer = _make_user(db, cleanup)
    private = pitch_service.create_pitch(
        db, owner, _create_in(name="Private Pitch", base_lat=6.45, base_lng=3.39)
    )
    cleanup(pitch_id=private.id)

    nearby = pitch_service.list_nearby(db, viewer, lat=6.4501, lng=3.3901)
    assert all(p.id != private.id for p in nearby)


def test_nearby_includes_own_and_public(db: Session, cleanup):
    owner = _make_user(db, cleanup)
    viewer = _make_user(db, cleanup)

    own = pitch_service.create_pitch(
        db, viewer, _create_in(name="My Pitch", base_lat=6.45, base_lng=3.39)
    )
    cleanup(pitch_id=own.id)

    public = pitch_service.create_pitch(
        db,
        owner,
        _create_in(name="Public Pitch", base_lat=6.4502, base_lng=3.3902),
    )
    cleanup(pitch_id=public.id)
    pitch = db.get(Pitch, public.id)
    assert pitch is not None
    pitch.visibility = PitchVisibility.public
    db.add(pitch)
    db.commit()

    nearby = pitch_service.list_nearby(db, viewer, lat=6.4501, lng=3.3901)
    ids = {p.id for p in nearby}
    assert own.id in ids
    assert public.id in ids
    assert all(hasattr(p, "distance_meters") for p in nearby)


def test_check_similar_finds_intersecting(db: Session, cleanup):
    user = _make_user(db, cleanup)
    created = pitch_service.create_pitch(db, user, _create_in())
    cleanup(pitch_id=created.id)

    similar = pitch_service.check_similar(db, user, _corners())
    assert any(p.id == created.id for p in similar)


def test_check_similar_excludes_others_private(db: Session, cleanup):
    owner = _make_user(db, cleanup)
    viewer = _make_user(db, cleanup)
    private = pitch_service.create_pitch(db, owner, _create_in())
    cleanup(pitch_id=private.id)

    similar = pitch_service.check_similar(db, viewer, _corners())
    assert all(p.id != private.id for p in similar)


def test_save_pitch_idempotent_and_404_private(db: Session, cleanup):
    owner = _make_user(db, cleanup)
    viewer = _make_user(db, cleanup)
    private = pitch_service.create_pitch(db, owner, _create_in())
    cleanup(pitch_id=private.id)

    with pytest.raises(HTTPException) as exc:
        pitch_service.save_pitch(db, viewer, private.id)
    assert exc.value.status_code == 404

    public = pitch_service.create_pitch(
        db, owner, _create_in(name="Public", base_lat=6.46, base_lng=3.40)
    )
    cleanup(pitch_id=public.id)
    pitch = db.get(Pitch, public.id)
    assert pitch is not None
    pitch.visibility = PitchVisibility.public
    db.add(pitch)
    db.commit()

    first = pitch_service.save_pitch(db, viewer, public.id)
    second = pitch_service.save_pitch(db, viewer, public.id)
    assert first.id == second.id == public.id
    assert len(pitch_service.list_saved(db, viewer)) == 1
