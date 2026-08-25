import uuid

from fastapi import HTTPException, status
from geoalchemy2 import Geography, Geometry
from geoalchemy2.elements import WKTElement
from geoalchemy2.functions import (
    ST_Centroid,
    ST_Collect,
    ST_ConvexHull,
    ST_Distance,
    ST_DWithin,
    ST_Intersects,
)
from geoalchemy2.shape import to_shape
from sqlalchemy import cast, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.models.pitch import Pitch, PitchVisibility, UserSavedPitch
from app.models.user import User
from app.schemas.pitch import (
    PitchCornersIn,
    PitchCreateIn,
    PitchNearbyOut,
    PitchRead,
)
from app.schemas.profile import LocationIn, LocationOut


def _point_wkt(loc: LocationIn | dict) -> WKTElement:
    if isinstance(loc, dict):
        lng, lat = loc["lng"], loc["lat"]
    else:
        lng, lat = loc.lng, loc.lat
    return WKTElement(f"POINT({lng} {lat})", srid=4326)


def _as_geom(expr):
    return cast(expr, Geometry)


def _location_to_out(location) -> LocationOut:
    point = to_shape(location)
    return LocationOut(lat=point.y, lng=point.x)


def _serialize_pitch(pitch: Pitch) -> PitchRead:
    return PitchRead(
        id=pitch.id,
        name=pitch.name,
        created_by_user_id=pitch.created_by_user_id,
        visibility=pitch.visibility,
        verified=pitch.verified,
        end_a_corner_1=_location_to_out(pitch.end_a_corner_1),
        end_a_corner_2=_location_to_out(pitch.end_a_corner_2),
        end_b_corner_1=_location_to_out(pitch.end_b_corner_1),
        end_b_corner_2=_location_to_out(pitch.end_b_corner_2),
        created_at=pitch.created_at,
    )


def _visible_pitch_filter(user_id: uuid.UUID):
    return or_(
        Pitch.created_by_user_id == user_id,
        Pitch.visibility == PitchVisibility.public,
    )


def _pitch_hull(pitch: type[Pitch] | Pitch):
    return ST_ConvexHull(
        ST_Collect(
            ST_Collect(
                _as_geom(pitch.end_a_corner_1),
                _as_geom(pitch.end_a_corner_2),
            ),
            ST_Collect(
                _as_geom(pitch.end_b_corner_1),
                _as_geom(pitch.end_b_corner_2),
            ),
        )
    )


def _pitch_centroid_geog(pitch: type[Pitch] | Pitch):
    return cast(ST_Centroid(_pitch_hull(pitch)), Geography)


def _corners_hull(corners: PitchCornersIn):
    return ST_ConvexHull(
        ST_Collect(
            ST_Collect(
                _as_geom(_point_wkt(corners.end_a_corner_1)),
                _as_geom(_point_wkt(corners.end_a_corner_2)),
            ),
            ST_Collect(
                _as_geom(_point_wkt(corners.end_b_corner_1)),
                _as_geom(_point_wkt(corners.end_b_corner_2)),
            ),
        )
    )


def _corners_centroid_geog(corners: PitchCornersIn):
    return cast(ST_Centroid(_corners_hull(corners)), Geography)


def get_visible_pitch(db: Session, pitch_id: uuid.UUID, user: User) -> Pitch:
    pitch = (
        db.query(Pitch)
        .filter(Pitch.id == pitch_id, _visible_pitch_filter(user.id))
        .one_or_none()
    )
    if pitch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Pitch not found",
        )
    return pitch


def ensure_saved(db: Session, user: User, pitch: Pitch) -> UserSavedPitch:
    existing = (
        db.query(UserSavedPitch)
        .filter(
            UserSavedPitch.user_id == user.id,
            UserSavedPitch.pitch_id == pitch.id,
        )
        .one_or_none()
    )
    if existing is not None:
        return existing

    saved = UserSavedPitch(user_id=user.id, pitch_id=pitch.id)
    try:
        with db.begin_nested():
            db.add(saved)
            db.flush()
    except IntegrityError:
        raced = (
            db.query(UserSavedPitch)
            .filter(
                UserSavedPitch.user_id == user.id,
                UserSavedPitch.pitch_id == pitch.id,
            )
            .one_or_none()
        )
        if raced is not None:
            return raced
        raise
    return saved


def list_nearby(
    db: Session, user: User, lat: float, lng: float
) -> list[PitchNearbyOut]:
    device = cast(WKTElement(f"POINT({lng} {lat})", srid=4326), Geography)
    centroid = _pitch_centroid_geog(Pitch)
    distance = ST_Distance(centroid, device)

    rows = (
        db.query(Pitch, distance.label("distance_meters"))
        .filter(
            _visible_pitch_filter(user.id),
            ST_DWithin(centroid, device, settings.pitch_nearby_radius_meters),
        )
        .order_by(distance)
        .limit(settings.pitch_suggest_limit)
        .all()
    )
    return [
        PitchNearbyOut(
            **_serialize_pitch(pitch).model_dump(),
            distance_meters=float(dist),
        )
        for pitch, dist in rows
    ]


def check_similar(
    db: Session, user: User, corners: PitchCornersIn
) -> list[PitchRead]:
    new_hull = _corners_hull(corners)
    new_centroid = _corners_centroid_geog(corners)
    existing_hull = _pitch_hull(Pitch)
    existing_centroid = _pitch_centroid_geog(Pitch)

    pitches = (
        db.query(Pitch)
        .filter(
            _visible_pitch_filter(user.id),
            or_(
                ST_Intersects(new_hull, existing_hull),
                ST_DWithin(
                    existing_centroid,
                    new_centroid,
                    settings.pitch_similar_centroid_meters,
                ),
            ),
        )
        .limit(settings.pitch_suggest_limit)
        .all()
    )
    return [_serialize_pitch(p) for p in pitches]


def create_pitch(db: Session, user: User, data: PitchCreateIn) -> PitchRead:
    pitch = Pitch(
        name=data.name,
        created_by_user_id=user.id,
        visibility=PitchVisibility.private,
        verified=False,
        end_a_corner_1=_point_wkt(data.end_a_corner_1),
        end_a_corner_2=_point_wkt(data.end_a_corner_2),
        end_b_corner_1=_point_wkt(data.end_b_corner_1),
        end_b_corner_2=_point_wkt(data.end_b_corner_2),
    )
    db.add(pitch)
    db.flush()
    ensure_saved(db, user, pitch)
    db.commit()
    db.refresh(pitch)
    return _serialize_pitch(pitch)


def list_saved(db: Session, user: User) -> list[PitchRead]:
    pitches = (
        db.query(Pitch)
        .join(UserSavedPitch, UserSavedPitch.pitch_id == Pitch.id)
        .filter(UserSavedPitch.user_id == user.id)
        .order_by(UserSavedPitch.saved_at.desc())
        .all()
    )
    return [_serialize_pitch(p) for p in pitches]


def save_pitch(db: Session, user: User, pitch_id: uuid.UUID) -> PitchRead:
    pitch = get_visible_pitch(db, pitch_id, user)
    ensure_saved(db, user, pitch)
    db.commit()
    db.refresh(pitch)
    return _serialize_pitch(pitch)


def unsave_pitch(db: Session, user: User, pitch_id: uuid.UUID) -> None:
    saved = (
        db.query(UserSavedPitch)
        .filter(
            UserSavedPitch.user_id == user.id,
            UserSavedPitch.pitch_id == pitch_id,
        )
        .one_or_none()
    )
    if saved is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Saved pitch not found",
        )
    db.delete(saved)
    db.commit()
