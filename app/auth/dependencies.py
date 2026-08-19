from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth.jwt import TokenClaims, verify_token
from app.config.database import get_db
from app.models.user import User
from app.services.identity import resolve_user

security = HTTPBearer()


def get_token_claims(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
) -> TokenClaims:
    return verify_token(credentials.credentials)


def get_current_user(
    claims: Annotated[TokenClaims, Depends(get_token_claims)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    return resolve_user(db, claims)
