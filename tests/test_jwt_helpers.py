from app.auth.jwt import provider_from_sub
from fastapi import HTTPException
import pytest


def test_provider_from_sub_mapping():
    assert provider_from_sub("google-oauth2|abc") == "google"
    assert provider_from_sub("apple|xyz") == "apple"
    assert provider_from_sub("email|123") == "email"


def test_provider_from_sub_unsupported():
    with pytest.raises(HTTPException) as exc:
        provider_from_sub("facebook|abc")
    assert exc.value.status_code == 400
