from app.auth.jwt import profile_from_payload, provider_from_sub
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


def test_profile_from_standard_email_claims():
    email, verified = profile_from_payload(
        {"email": "a@example.com", "email_verified": True}
    )
    assert email == "a@example.com"
    assert verified is True


def test_profile_from_namespaced_email_claims():
    email, verified = profile_from_payload(
        {
            "https://api.eleven.app/email": "b@example.com",
            "https://api.eleven.app/email_verified": True,
        }
    )
    assert email == "b@example.com"
    assert verified is True
