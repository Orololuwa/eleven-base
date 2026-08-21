import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from geoalchemy2.elements import WKTElement
from geoalchemy2.shape import to_shape
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.models.user import User
from app.modules.profiles import cloudinary_client
from app.modules.profiles.models import (
    PlayerPosition,
    PlayerProfile,
    ProfileVisibility,
)
from app.modules.profiles.schemas import (
    AvatarConfirmIn,
    AvatarSignatureOut,
    LocationOut,
    PositionOut,
    PositionSetIn,
    ProfileRead,
    ProfileReadPublic,
    ProfileUpdate,
)


def _location_to_out(location) -> LocationOut | None:
    if location is None:
        return None
    point = to_shape(location)
    return LocationOut(lat=point.y, lng=point.x)


def _serialize_full(profile: PlayerProfile) -> ProfileRead:
    return ProfileRead(
        id=profile.id,
        user_id=profile.user_id,
        display_name=profile.display_name,
        date_of_birth=profile.date_of_birth,
        preferred_foot=profile.preferred_foot,
        height_cm=profile.height_cm,
        skill_level=profile.skill_level,
        bio=profile.bio,
        location=_location_to_out(profile.location),
        visibility=profile.visibility,
        avatar_public_id=profile.avatar_public_id,
        avatar_url=profile.avatar_url,
        avatar_updated_at=profile.avatar_updated_at,
        onboarding_completed=profile.onboarding_completed,
        positions=[
            PositionOut(position=p.position, is_preferred=p.is_preferred)
            for p in profile.positions
        ],
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


def _serialize_public(profile: PlayerProfile) -> ProfileReadPublic:
    return ProfileReadPublic(
        user_id=profile.user_id,
        display_name=profile.display_name,
        preferred_foot=profile.preferred_foot,
        height_cm=profile.height_cm,
        skill_level=profile.skill_level,
        bio=profile.bio,
        avatar_url=profile.avatar_url,
        avatar_updated_at=profile.avatar_updated_at,
        positions=[
            PositionOut(position=p.position, is_preferred=p.is_preferred)
            for p in profile.positions
        ],
    )


def _load_profile(db: Session, user_id: uuid.UUID) -> PlayerProfile | None:
    return (
        db.query(PlayerProfile)
        .options(joinedload(PlayerProfile.positions))
        .filter(PlayerProfile.user_id == user_id)
        .one_or_none()
    )


def _has_preferred_position(profile: PlayerProfile) -> bool:
    return any(p.is_preferred for p in profile.positions)


def get_or_create_profile(db: Session, user: User) -> PlayerProfile:
    existing = _load_profile(db, user.id)
    if existing is not None:
        return existing

    profile = PlayerProfile(user_id=user.id, display_name="")
    db.add(profile)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raced = _load_profile(db, user.id)
        if raced is not None:
            return raced
        raise
    loaded = _load_profile(db, user.id)
    assert loaded is not None
    return loaded


def get_my_profile(db: Session, user: User) -> ProfileRead:
    profile = get_or_create_profile(db, user)
    return _serialize_full(profile)


def update_profile(db: Session, user: User, data: ProfileUpdate) -> ProfileRead:
    profile = get_or_create_profile(db, user)
    payload = data.model_dump(exclude_unset=True)

    if "location" in payload:
        loc = payload.pop("location")
        if loc is None:
            profile.location = None
        else:
            profile.location = WKTElement(
                f"POINT({loc['lng']} {loc['lat']})", srid=4326
            )

    onboarding = payload.pop("onboarding_completed", None)

    for field, value in payload.items():
        setattr(profile, field, value)

    if onboarding is True:
        # Re-load positions in case they were not eagerly available
        db.refresh(profile, attribute_names=["positions"])
        if not profile.positions or not _has_preferred_position(profile):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "completed onboarding requires at least one position "
                    "with a preferred flag"
                ),
            )
        profile.onboarding_completed = True
    elif onboarding is False:
        profile.onboarding_completed = False

    db.add(profile)
    db.commit()
    profile = _load_profile(db, user.id)
    assert profile is not None
    return _serialize_full(profile)


def get_profile_for_viewer(
    db: Session, target_user_id: uuid.UUID, viewer: User
) -> ProfileRead | ProfileReadPublic:
    if target_user_id == viewer.id:
        return get_my_profile(db, viewer)

    profile = _load_profile(db, target_user_id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found",
        )
    if profile.visibility == ProfileVisibility.private:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Profile not found",
        )
    return _serialize_public(profile)


def replace_positions(
    db: Session, user: User, data: PositionSetIn
) -> list[PositionOut]:
    profile = get_or_create_profile(db, user)

    # Unset preferred first to avoid violating the partial unique index.
    for row in profile.positions:
        row.is_preferred = False
    db.flush()

    for row in list(profile.positions):
        db.delete(row)
    db.flush()

    preferred_code = next(p.position for p in data.positions if p.is_preferred)
    for item in data.positions:
        db.add(
            PlayerPosition(
                player_profile_id=profile.id,
                position=item.position,
                is_preferred=False,
            )
        )
    db.flush()

    preferred_row = (
        db.query(PlayerPosition)
        .filter(
            PlayerPosition.player_profile_id == profile.id,
            PlayerPosition.position == preferred_code,
        )
        .one()
    )
    preferred_row.is_preferred = True
    db.add(preferred_row)
    db.commit()

    profile = _load_profile(db, user.id)
    assert profile is not None
    return [
        PositionOut(position=p.position, is_preferred=p.is_preferred)
        for p in profile.positions
    ]


def get_avatar_signature(user: User) -> AvatarSignatureOut:
    folder = f"eleven/avatars/{user.id}"
    try:
        signed = cloudinary_client.generate_upload_signature(folder=folder)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(exc),
        ) from exc
    return AvatarSignatureOut(**signed)


def confirm_avatar(
    db: Session, user: User, data: AvatarConfirmIn
) -> ProfileRead:
    profile = get_or_create_profile(db, user)
    profile.avatar_public_id = data.public_id
    profile.avatar_url = data.secure_url
    profile.avatar_updated_at = datetime.now(timezone.utc)
    db.add(profile)
    db.commit()
    profile = _load_profile(db, user.id)
    assert profile is not None
    return _serialize_full(profile)


def delete_avatar(db: Session, user: User) -> None:
    profile = get_or_create_profile(db, user)
    if profile.avatar_public_id:
        try:
            cloudinary_client.destroy_asset(profile.avatar_public_id)
        except RuntimeError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=str(exc),
            ) from exc
    profile.avatar_public_id = None
    profile.avatar_url = None
    profile.avatar_updated_at = None
    db.add(profile)
    db.commit()
