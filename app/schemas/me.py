from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class IdentityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    provider: str
    auth0_sub: str
    created_at: datetime


class MeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str | None
    email_verified: bool
    identities: list[IdentityOut]
    created_at: datetime
    updated_at: datetime


class LinkIdentityRequest(BaseModel):
    secondary_token: str = Field(..., min_length=1)
