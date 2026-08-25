from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.config.database import get_db
from app.models.user import User
from app.schemas.pitch import (
    PitchCornersIn,
    PitchCreateIn,
    PitchNearbyOut,
    PitchRead,
)
from app.services import pitch as pitch_service

router = APIRouter(prefix="/pitches", tags=["pitches"])


@router.get("/nearby", response_model=list[PitchNearbyOut])
def get_nearby_pitches(
    lat: Annotated[float, Query(ge=-90, le=90)],
    lng: Annotated[float, Query(ge=-180, le=180)],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[PitchNearbyOut]:
    return pitch_service.list_nearby(db, user, lat, lng)


@router.post("/check-similar", response_model=list[PitchRead])
def post_check_similar(
    body: PitchCornersIn,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[PitchRead]:
    return pitch_service.check_similar(db, user, body)


@router.post("", response_model=PitchRead, status_code=status.HTTP_201_CREATED)
def post_pitch(
    body: PitchCreateIn,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> PitchRead:
    return pitch_service.create_pitch(db, user, body)


@router.get("/saved", response_model=list[PitchRead])
def get_saved_pitches(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[PitchRead]:
    return pitch_service.list_saved(db, user)


@router.post("/{pitch_id}/save", response_model=PitchRead)
def post_save_pitch(
    pitch_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> PitchRead:
    return pitch_service.save_pitch(db, user, pitch_id)


@router.delete("/{pitch_id}/save", status_code=status.HTTP_204_NO_CONTENT)
def delete_save_pitch(
    pitch_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    pitch_service.unsave_pitch(db, user, pitch_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
