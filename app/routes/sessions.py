from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.config.database import get_db
from app.models.user import User
from app.schemas.session import (
    SessionCreateIn,
    SessionFinalizeIn,
    SessionRead,
    SessionStartIn,
    TrackPointsIn,
    TrackPointsOut,
)
from app.services import session as session_service

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", response_model=SessionRead, status_code=status.HTTP_201_CREATED)
def post_session(
    body: SessionCreateIn,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> SessionRead:
    return session_service.create_session(db, user, body)


@router.post("/{session_id}/start", response_model=SessionRead)
def post_start_session(
    session_id: UUID,
    body: SessionStartIn,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> SessionRead:
    return session_service.start_session(db, user, session_id, body)


@router.post("/{session_id}/finalize", response_model=SessionRead)
def post_finalize_session(
    session_id: UUID,
    body: SessionFinalizeIn,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> SessionRead:
    return session_service.finalize_session(db, user, session_id, body)


@router.post("/{session_id}/track-points", response_model=TrackPointsOut)
def post_track_points(
    session_id: UUID,
    body: TrackPointsIn,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> TrackPointsOut:
    return session_service.upload_track_points(db, user, session_id, body)
