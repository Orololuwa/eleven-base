from dataclasses import dataclass

import httpx
import jwt
from cachetools import TTLCache
from fastapi import HTTPException, status
from jwt import PyJWKClient

from app.config.settings import settings

# Cache JWKS client for 10 minutes
_jwks_cache: TTLCache = TTLCache(maxsize=1, ttl=600)


@dataclass(frozen=True)
class TokenClaims:
    sub: str
    email: str | None
    email_verified: bool


def _get_jwks_client() -> PyJWKClient:
    if "jwks_client" not in _jwks_cache:
        if not settings.auth0_domain:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Auth0 is not configured",
            )
        _jwks_cache["jwks_client"] = PyJWKClient(
            settings.auth0_jwks_url,
            cache_keys=True,
            lifespan=600,
        )
    return _jwks_cache["jwks_client"]


def provider_from_sub(auth0_sub: str) -> str:
    """Map Auth0 sub prefix to IdentityProvider value."""
    prefix = auth0_sub.split("|", 1)[0]
    mapping = {
        "google-oauth2": "google",
        "apple": "apple",
        "email": "email",
    }
    provider = mapping.get(prefix)
    if provider is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported identity provider: {prefix}",
        )
    return provider


def verify_token(token: str) -> TokenClaims:
    """Verify an Auth0 RS256 JWT and return normalized claims."""
    if not settings.auth0_domain or not settings.auth0_audience:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Auth0 is not configured",
        )

    try:
        jwks_client = _get_jwks_client()
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=settings.auth0_algorithms_list,
            audience=settings.auth0_audience,
            issuer=settings.auth0_issuer,
        )
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except jwt.InvalidAudienceError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token audience",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except jwt.InvalidIssuerError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token issuer",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except (jwt.PyJWTError, httpx.HTTPError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    sub = payload.get("sub")
    if not sub or not isinstance(sub, str):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject",
            headers={"WWW-Authenticate": "Bearer"},
        )

    email = payload.get("email")
    if email is not None and not isinstance(email, str):
        email = None

    email_verified = bool(payload.get("email_verified", False))

    return TokenClaims(sub=sub, email=email, email_verified=email_verified)
