from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.config.database import get_db
from app.models.session import SessionType
from app.models.user import User
from app.schemas.session import (
    SessionCalendar,
    SessionCreateIn,
    SessionDetail,
    SessionFinalizeIn,
    SessionListPage,
    SessionRead,
    SessionStartIn,
    SessionTitleOut,
    SessionTitleUpdate,
    TrackPointsIn,
    TrackPointsOut,
    WeeklySessionWindow,
)
from app.services import session as session_service

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get("", response_model=SessionListPage)
def get_sessions(
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    session_type: SessionType | None = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> SessionListPage:
    return session_service.list_history(db, user, session_type, cursor, limit)


@router.get("/calendar", response_model=SessionCalendar)
def get_sessions_calendar(
    month: str,
    tz: str,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
    session_type: SessionType | None = None,
) -> SessionCalendar:
    return session_service.get_history_calendar(db, user, month, tz, session_type)


@router.get("/weekly", response_model=WeeklySessionWindow)
def get_sessions_weekly(
    start: Annotated[
        datetime,
        Query(description="Inclusive ISO-8601 instant with an offset"),
    ],
    end: Annotated[
        datetime,
        Query(description="Exclusive ISO-8601 instant with an offset"),
    ],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> WeeklySessionWindow:
    return session_service.get_weekly_window(db, user, start, end)


@router.post("", response_model=SessionRead, status_code=status.HTTP_201_CREATED)
def post_session(
    body: SessionCreateIn,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> SessionRead:
    return session_service.create_session(db, user, body)


@router.get("/{session_id}", response_model=SessionDetail)
def get_session(
    session_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> SessionDetail:
    return session_service.get_session_detail(db, user, session_id)


@router.patch("/{session_id}", response_model=SessionTitleOut)
def patch_session(
    session_id: UUID,
    body: SessionTitleUpdate,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> SessionTitleOut:
    return session_service.rename_session(db, user, session_id, body)


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(
    session_id: UUID,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    session_service.delete_session(db, user, session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


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
