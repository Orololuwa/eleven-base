from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.config.database import get_db
from app.models.user import User
from app.schemas.profile import (
    AvatarConfirmIn,
    AvatarSignatureOut,
    PositionOut,
    PositionSetIn,
    ProfileRead,
    ProfileReadPublic,
    ProfileUpdate,
)
from app.services import profile as profile_service

router = APIRouter(prefix="/profiles", tags=["profiles"])


@router.get("/me", response_model=ProfileRead)
def get_my_profile(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ProfileRead:
    return profile_service.get_my_profile(db, user)


@router.patch("/me", response_model=ProfileRead)
def patch_my_profile(
    body: ProfileUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ProfileRead:
    return profile_service.update_profile(db, user, body)


@router.put("/me/positions", response_model=list[PositionOut])
def put_my_positions(
    body: PositionSetIn,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> list[PositionOut]:
    return profile_service.replace_positions(db, user, body)


@router.post("/me/avatar/signature", response_model=AvatarSignatureOut)
def post_avatar_signature(
    user: Annotated[User, Depends(get_current_user)],
) -> AvatarSignatureOut:
    return profile_service.get_avatar_signature(user)


@router.patch("/me/avatar", response_model=ProfileRead)
def patch_avatar(
    body: AvatarConfirmIn,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ProfileRead:
    return profile_service.confirm_avatar(db, user, body)


@router.delete("/me/avatar", status_code=status.HTTP_204_NO_CONTENT)
def delete_avatar(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    profile_service.delete_avatar(db, user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{user_id}",
    response_model=ProfileRead | ProfileReadPublic,
)
def get_profile(
    user_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> ProfileRead | ProfileReadPublic:
    return profile_service.get_profile_for_viewer(db, user_id, user)
