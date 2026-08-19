from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth.dependencies import get_current_user
from app.auth.jwt import TokenClaims, verify_token
from app.config.database import get_db
from app.models.user import User
from app.schemas.me import LinkIdentityRequest, MeOut
from app.services.identity import link_identity

router = APIRouter(tags=["me"])


def _serialize_me(user: User) -> MeOut:
    return MeOut(
        id=user.id,
        email=user.email,
        email_verified=user.email_verified,
        identities=[
            {
                "provider": identity.provider.value
                if hasattr(identity.provider, "value")
                else identity.provider,
                "auth0_sub": identity.auth0_sub,
                "created_at": identity.created_at,
            }
            for identity in user.identities
        ],
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


@router.get("/me", response_model=MeOut)
def get_me(user: Annotated[User, Depends(get_current_user)]) -> MeOut:
    """Resolve the Bearer JWT to a local user (create / merge / attach per §4)."""
    return _serialize_me(user)


@router.post("/me/link", response_model=MeOut)
def link_me(
    body: LinkIdentityRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_db)],
) -> MeOut:
    """Attach a second Auth0 identity to the current user (in-app linking)."""
    secondary_claims: TokenClaims = verify_token(body.secondary_token)
    updated = link_identity(db, current_user=user, secondary_claims=secondary_claims)
    return _serialize_me(updated)
