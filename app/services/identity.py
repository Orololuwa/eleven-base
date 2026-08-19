import uuid

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.auth.jwt import TokenClaims, provider_from_sub
from app.models.identity import IdentityProvider, UserIdentity
from app.models.user import User


def _get_identity_by_sub(db: Session, auth0_sub: str) -> UserIdentity | None:
    return (
        db.query(UserIdentity)
        .options(joinedload(UserIdentity.user).joinedload(User.identities))
        .filter(UserIdentity.auth0_sub == auth0_sub)
        .one_or_none()
    )


def _get_user_by_email(db: Session, email: str) -> User | None:
    return (
        db.query(User)
        .options(joinedload(User.identities))
        .filter(User.email == email)
        .one_or_none()
    )


def _create_user_with_identity(
    db: Session,
    *,
    email: str | None,
    email_verified: bool,
    auth0_sub: str,
    provider: IdentityProvider,
) -> User:
    user = User(email=email, email_verified=email_verified)
    identity = UserIdentity(
        user=user,
        auth0_sub=auth0_sub,
        provider=provider,
    )
    db.add(user)
    db.add(identity)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = _get_identity_by_sub(db, auth0_sub)
        if existing is not None:
            return existing.user
        raise
    db.refresh(user)
    return _user_with_identities(db, user.id)


def _user_with_identities(db: Session, user_id: uuid.UUID) -> User:
    return (
        db.query(User)
        .options(joinedload(User.identities))
        .filter(User.id == user_id)
        .one()
    )


def _backfill_email(db: Session, user: User, claims: TokenClaims) -> User:
    if not claims.email:
        return user
    changed = False
    if user.email is None:
        user.email = claims.email
        changed = True
    if claims.email_verified and not user.email_verified:
        user.email_verified = True
        changed = True
    if not changed:
        return user
    db.add(user)
    db.commit()
    return _user_with_identities(db, user.id)


def resolve_user(db: Session, claims: TokenClaims) -> User:
    """Resolve auth0_sub to a user per identity rules (§4).

    - Existing auth0_sub → that user
    - Apple → never email-merge; create new user if unknown
    - Google / Email → merge on email match, else create
    """
    existing = _get_identity_by_sub(db, claims.sub)
    if existing is not None:
        return _backfill_email(db, existing.user, claims)

    provider_value = provider_from_sub(claims.sub)
    provider = IdentityProvider(provider_value)

    if provider == IdentityProvider.apple:
        return _create_user_with_identity(
            db,
            email=claims.email,
            email_verified=claims.email_verified,
            auth0_sub=claims.sub,
            provider=provider,
        )

    if claims.email:
        matched = _get_user_by_email(db, claims.email)
        if matched is not None:
            identity = UserIdentity(
                user_id=matched.id,
                auth0_sub=claims.sub,
                provider=provider,
            )
            db.add(identity)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                raced = _get_identity_by_sub(db, claims.sub)
                if raced is not None:
                    return raced.user
                raise
            return _user_with_identities(db, matched.id)

    return _create_user_with_identity(
        db,
        email=claims.email,
        email_verified=claims.email_verified,
        auth0_sub=claims.sub,
        provider=provider,
    )


def link_identity(
    db: Session,
    *,
    current_user: User,
    secondary_claims: TokenClaims,
) -> User:
    """Attach a secondary Auth0 identity to the already-authenticated user."""
    provider_value = provider_from_sub(secondary_claims.sub)
    provider = IdentityProvider(provider_value)

    existing = _get_identity_by_sub(db, secondary_claims.sub)
    if existing is not None:
        if existing.user_id == current_user.id:
            return (
                db.query(User)
                .options(joinedload(User.identities))
                .filter(User.id == current_user.id)
                .one()
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Identity is already linked to another account",
        )

    identity = UserIdentity(
        user_id=current_user.id,
        auth0_sub=secondary_claims.sub,
        provider=provider,
    )
    db.add(identity)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raced = _get_identity_by_sub(db, secondary_claims.sub)
        if raced is not None and raced.user_id == current_user.id:
            return (
                db.query(User)
                .options(joinedload(User.identities))
                .filter(User.id == current_user.id)
                .one()
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Identity is already linked to another account",
        )

    return (
        db.query(User)
        .options(joinedload(User.identities))
        .filter(User.id == current_user.id)
        .one()
    )


def get_user_by_id(db: Session, user_id: uuid.UUID) -> User | None:
    return (
        db.query(User)
        .options(joinedload(User.identities))
        .filter(User.id == user_id)
        .one_or_none()
    )
