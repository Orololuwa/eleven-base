import uuid
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.config.database import SessionLocal
from app.models.user import User
from app.modules.profiles.models import (
    PlayerProfile,
    PositionCode,
    ProfileVisibility,
)
from app.modules.profiles.schemas import (
    AvatarConfirmIn,
    PositionSetIn,
    ProfileUpdate,
)
from app.modules.profiles.service import (
    confirm_avatar,
    delete_avatar,
    get_or_create_profile,
    get_profile_for_viewer,
    replace_positions,
    update_profile,
)


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

    def track(user_id: uuid.UUID):
        user_ids.append(user_id)

    yield track

    db.expire_all()
    for user_id in user_ids:
        profile = (
            db.query(PlayerProfile).filter(PlayerProfile.user_id == user_id).one_or_none()
        )
        if profile is not None:
            db.delete(profile)
        user = db.get(User, user_id)
        if user is not None:
            db.delete(user)
    db.commit()


def _make_user(db: Session, cleanup) -> User:
    user = User(email=f"profile-{uuid.uuid4()}@example.com", email_verified=True)
    db.add(user)
    db.commit()
    db.refresh(user)
    cleanup(user.id)
    return user


# --- Schema validation (no DB) ---


def test_position_set_accepts_valid():
    data = PositionSetIn.model_validate(
        [
            {"position": "ST", "is_preferred": True},
            {"position": "CAM", "is_preferred": False},
        ]
    )
    assert len(data.positions) == 2


def test_position_set_rejects_duplicates():
    with pytest.raises(ValidationError):
        PositionSetIn.model_validate(
            [
                {"position": "ST", "is_preferred": True},
                {"position": "ST", "is_preferred": False},
            ]
        )


def test_position_set_rejects_no_preferred():
    with pytest.raises(ValidationError):
        PositionSetIn.model_validate(
            [
                {"position": "ST", "is_preferred": False},
                {"position": "CAM", "is_preferred": False},
            ]
        )


def test_position_set_rejects_two_preferred():
    with pytest.raises(ValidationError):
        PositionSetIn.model_validate(
            [
                {"position": "ST", "is_preferred": True},
                {"position": "CAM", "is_preferred": True},
            ]
        )


def test_position_set_rejects_more_than_five():
    with pytest.raises(ValidationError):
        PositionSetIn.model_validate(
            [
                {"position": "GK", "is_preferred": True},
                {"position": "CB", "is_preferred": False},
                {"position": "CM", "is_preferred": False},
                {"position": "ST", "is_preferred": False},
                {"position": "LW", "is_preferred": False},
                {"position": "RW", "is_preferred": False},
            ]
        )


def test_profile_update_rejects_bad_height():
    with pytest.raises(ValidationError):
        ProfileUpdate(height_cm=50)


def test_profile_update_rejects_long_bio():
    with pytest.raises(ValidationError):
        ProfileUpdate(bio="x" * 501)


# --- Service tests (require migrated DB + PostGIS) ---


def test_get_or_create_idempotent(db: Session, cleanup):
    user = _make_user(db, cleanup)
    first = get_or_create_profile(db, user)
    second = get_or_create_profile(db, user)
    assert first.id == second.id
    assert first.user_id == user.id
    assert first.display_name == ""


def test_replace_positions_sets_one_preferred(db: Session, cleanup):
    user = _make_user(db, cleanup)
    get_or_create_profile(db, user)
    result = replace_positions(
        db,
        user,
        PositionSetIn.model_validate(
            [
                {"position": "ST", "is_preferred": True},
                {"position": "CAM", "is_preferred": False},
                {"position": "CM", "is_preferred": False},
            ]
        ),
    )
    assert len(result) == 3
    preferred = [p for p in result if p.is_preferred]
    assert len(preferred) == 1
    assert preferred[0].position == PositionCode.ST


def test_replace_positions_can_swap_preferred(db: Session, cleanup):
    user = _make_user(db, cleanup)
    get_or_create_profile(db, user)
    replace_positions(
        db,
        user,
        PositionSetIn.model_validate(
            [
                {"position": "ST", "is_preferred": True},
                {"position": "CAM", "is_preferred": False},
            ]
        ),
    )
    result = replace_positions(
        db,
        user,
        PositionSetIn.model_validate(
            [
                {"position": "CAM", "is_preferred": True},
                {"position": "LW", "is_preferred": False},
            ]
        ),
    )
    assert {p.position for p in result} == {PositionCode.CAM, PositionCode.LW}
    assert next(p for p in result if p.is_preferred).position == PositionCode.CAM


def test_onboarding_requires_positions(db: Session, cleanup):
    user = _make_user(db, cleanup)
    get_or_create_profile(db, user)
    with pytest.raises(HTTPException) as exc:
        update_profile(db, user, ProfileUpdate(onboarding_completed=True))
    assert exc.value.status_code == 422


def test_onboarding_succeeds_with_positions(db: Session, cleanup):
    user = _make_user(db, cleanup)
    get_or_create_profile(db, user)
    replace_positions(
        db,
        user,
        PositionSetIn.model_validate(
            [{"position": "ST", "is_preferred": True}]
        ),
    )
    profile = update_profile(db, user, ProfileUpdate(onboarding_completed=True))
    assert profile.onboarding_completed is True


def test_private_profile_hidden_from_others(db: Session, cleanup):
    owner = _make_user(db, cleanup)
    viewer = _make_user(db, cleanup)
    get_or_create_profile(db, owner)
    update_profile(db, owner, ProfileUpdate(visibility=ProfileVisibility.private))

    with pytest.raises(HTTPException) as exc:
        get_profile_for_viewer(db, owner.id, viewer)
    assert exc.value.status_code == 404


def test_public_profile_visible_to_others(db: Session, cleanup):
    owner = _make_user(db, cleanup)
    viewer = _make_user(db, cleanup)
    get_or_create_profile(db, owner)
    update_profile(
        db,
        owner,
        ProfileUpdate(display_name="Striker", visibility=ProfileVisibility.public),
    )
    public = get_profile_for_viewer(db, owner.id, viewer)
    assert public.display_name == "Striker"
    assert not hasattr(public, "date_of_birth") or "date_of_birth" not in public.model_dump()


def test_confirm_and_delete_avatar(db: Session, cleanup):
    user = _make_user(db, cleanup)
    get_or_create_profile(db, user)
    confirmed = confirm_avatar(
        db,
        user,
        AvatarConfirmIn(
            public_id="eleven/avatars/x",
            secure_url="https://res.cloudinary.com/demo/image/upload/x.jpg",
        ),
    )
    assert confirmed.avatar_public_id == "eleven/avatars/x"
    assert confirmed.avatar_url is not None
    assert confirmed.avatar_updated_at is not None

    with patch("app.modules.profiles.cloudinary_client.destroy_asset") as destroy:
        delete_avatar(db, user)
        destroy.assert_called_once_with("eleven/avatars/x")

    profile = get_or_create_profile(db, user)
    assert profile.avatar_public_id is None
    assert profile.avatar_url is None
    assert profile.avatar_updated_at is None
