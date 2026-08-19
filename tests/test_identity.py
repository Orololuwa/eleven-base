import uuid

import pytest
from sqlalchemy.orm import Session

from app.auth.jwt import TokenClaims
from app.config.database import SessionLocal
from app.models.identity import IdentityProvider, UserIdentity
from app.models.user import User
from app.services.identity import link_identity, resolve_user
from fastapi import HTTPException


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
    """Track emails/subs created during a test and remove them afterward."""
    emails: list[str] = []
    subs: list[str] = []

    def track(*, email: str | None = None, sub: str | None = None):
        if email:
            emails.append(email)
        if sub:
            subs.append(sub)

    yield track

    db.expire_all()
    user_ids: set[uuid.UUID] = set()
    if subs:
        identities = (
            db.query(UserIdentity).filter(UserIdentity.auth0_sub.in_(subs)).all()
        )
        for identity in identities:
            user_ids.add(identity.user_id)
            db.delete(identity)
    if emails:
        for user in db.query(User).filter(User.email.in_(emails)).all():
            user_ids.add(user.id)
    for user_id in user_ids:
        remaining = (
            db.query(UserIdentity).filter(UserIdentity.user_id == user_id).all()
        )
        for identity in remaining:
            db.delete(identity)
        user = db.get(User, user_id)
        if user is not None:
            db.delete(user)
    db.commit()


def _claims(sub: str, email: str | None = None, verified: bool = True) -> TokenClaims:
    return TokenClaims(sub=sub, email=email, email_verified=verified)


def test_resolve_existing_identity(db: Session, cleanup):
    email = f"existing-{uuid.uuid4()}@example.com"
    sub = f"google-oauth2|{uuid.uuid4()}"
    cleanup(email=email, sub=sub)

    user = User(email=email, email_verified=True)
    db.add(user)
    db.flush()
    db.add(
        UserIdentity(
            user_id=user.id, auth0_sub=sub, provider=IdentityProvider.google
        )
    )
    db.commit()

    resolved = resolve_user(db, _claims(sub, email))
    assert resolved.id == user.id
    assert len(resolved.identities) == 1


def test_resolve_existing_identity_backfills_email(db: Session, cleanup):
    email = f"backfill-{uuid.uuid4()}@example.com"
    sub = f"google-oauth2|{uuid.uuid4()}"
    cleanup(email=email, sub=sub)

    user = User(email=None, email_verified=False)
    db.add(user)
    db.flush()
    db.add(
        UserIdentity(
            user_id=user.id, auth0_sub=sub, provider=IdentityProvider.google
        )
    )
    db.commit()

    resolved = resolve_user(db, _claims(sub, email, verified=True))
    assert resolved.id == user.id
    assert resolved.email == email
    assert resolved.email_verified is True


def test_google_email_merge(db: Session, cleanup):
    email = f"merge-{uuid.uuid4()}@example.com"
    google_sub = f"google-oauth2|{uuid.uuid4()}"
    email_sub = f"email|{uuid.uuid4()}"
    cleanup(email=email, sub=google_sub)
    cleanup(sub=email_sub)

    first = resolve_user(db, _claims(google_sub, email))
    second = resolve_user(db, _claims(email_sub, email))

    assert second.id == first.id
    providers = {i.provider for i in second.identities}
    assert providers == {IdentityProvider.google, IdentityProvider.email}


def test_apple_never_email_merges(db: Session, cleanup):
    email = f"apple-{uuid.uuid4()}@example.com"
    google_sub = f"google-oauth2|{uuid.uuid4()}"
    apple_sub = f"apple|{uuid.uuid4()}"
    cleanup(email=email, sub=google_sub)
    cleanup(sub=apple_sub)

    google_user = resolve_user(db, _claims(google_sub, email))
    apple_user = resolve_user(db, _claims(apple_sub, email))

    assert apple_user.id != google_user.id
    assert len(apple_user.identities) == 1
    assert apple_user.identities[0].provider == IdentityProvider.apple


def test_link_identity_success(db: Session, cleanup):
    email = f"link-{uuid.uuid4()}@example.com"
    google_sub = f"google-oauth2|{uuid.uuid4()}"
    apple_sub = f"apple|{uuid.uuid4()}"
    cleanup(email=email, sub=google_sub)
    cleanup(sub=apple_sub)

    user = resolve_user(db, _claims(google_sub, email))
    linked = link_identity(
        db,
        current_user=user,
        secondary_claims=_claims(apple_sub, email),
    )

    assert linked.id == user.id
    providers = {i.provider for i in linked.identities}
    assert providers == {IdentityProvider.google, IdentityProvider.apple}


def test_link_identity_conflict(db: Session, cleanup):
    email_a = f"a-{uuid.uuid4()}@example.com"
    email_b = f"b-{uuid.uuid4()}@example.com"
    sub_a = f"google-oauth2|{uuid.uuid4()}"
    sub_b = f"apple|{uuid.uuid4()}"
    cleanup(email=email_a, sub=sub_a)
    cleanup(email=email_b, sub=sub_b)

    user_a = resolve_user(db, _claims(sub_a, email_a))
    user_b = resolve_user(db, _claims(sub_b, email_b))

    with pytest.raises(HTTPException) as exc:
        link_identity(
            db,
            current_user=user_a,
            secondary_claims=_claims(sub_b, email_b),
        )
    assert exc.value.status_code == 409
    assert user_b.id != user_a.id


def test_link_identity_idempotent(db: Session, cleanup):
    email = f"idem-{uuid.uuid4()}@example.com"
    google_sub = f"google-oauth2|{uuid.uuid4()}"
    apple_sub = f"apple|{uuid.uuid4()}"
    cleanup(email=email, sub=google_sub)
    cleanup(sub=apple_sub)

    user = resolve_user(db, _claims(google_sub, email))
    once = link_identity(db, current_user=user, secondary_claims=_claims(apple_sub))
    twice = link_identity(db, current_user=user, secondary_claims=_claims(apple_sub))

    assert once.id == twice.id == user.id
    assert len(twice.identities) == 2
