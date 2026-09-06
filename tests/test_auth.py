"""JWT verification tests — both signing schemes Supabase uses, without any network."""

from __future__ import annotations

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec

from app import auth
from app.config import Settings

SECRET = "test-hs256-secret-that-is-long-enough-0123456789"


def _claims(**overrides) -> dict:
    base = {
        "sub": "11111111-2222-3333-4444-555555555555",
        "email": "dor@northbound.test",
        "aud": "authenticated",
        "role": "authenticated",
        "iat": int(time.time()),
        "exp": int(time.time()) + 3600,
    }
    return {**base, **overrides}


@pytest.fixture
def hs_settings() -> Settings:
    return Settings(
        supabase_url="https://x.supabase.co", supabase_anon_key="anon", supabase_jwt_secret=SECRET
    )


def test_hs256_token_is_accepted(hs_settings):
    token = jwt.encode(_claims(), SECRET, algorithm="HS256")
    claims = auth.verify_token(token, hs_settings)
    assert claims["sub"] == "11111111-2222-3333-4444-555555555555"


def test_hs256_wrong_secret_is_rejected(hs_settings):
    token = jwt.encode(_claims(), "another-secret", algorithm="HS256")
    with pytest.raises(jwt.PyJWTError):
        auth.verify_token(token, hs_settings)


def test_expired_token_is_rejected(hs_settings):
    token = jwt.encode(_claims(exp=int(time.time()) - 10), SECRET, algorithm="HS256")
    with pytest.raises(jwt.ExpiredSignatureError):
        auth.verify_token(token, hs_settings)


def test_wrong_audience_is_rejected(hs_settings):
    token = jwt.encode(_claims(aud="anon"), SECRET, algorithm="HS256")
    with pytest.raises(jwt.InvalidAudienceError):
        auth.verify_token(token, hs_settings)


def test_hs256_without_configured_secret_is_rejected():
    settings = Settings(
        supabase_url="https://x.supabase.co", supabase_anon_key="anon", supabase_jwt_secret=None
    )
    token = jwt.encode(_claims(), SECRET, algorithm="HS256")
    with pytest.raises(ValueError, match="SUPABASE_JWT_SECRET"):
        auth.verify_token(token, settings)


def test_es256_token_verified_against_jwks_key(monkeypatch, hs_settings):
    """Simulates the current Supabase scheme: ES256 signed, public key served by JWKS."""
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key()
    token = jwt.encode(_claims(), private_key, algorithm="ES256", headers={"kid": "k1"})

    class _Key:
        key = public_key

    class _FakeJwks:
        def get_signing_key_from_jwt(self, _token):
            return _Key()

    monkeypatch.setattr(auth, "_jwks_client", lambda _url: _FakeJwks())
    claims = auth.verify_token(token, hs_settings)
    assert claims["email"] == "dor@northbound.test"


def test_es256_signed_by_other_key_is_rejected(monkeypatch, hs_settings):
    attacker = ec.generate_private_key(ec.SECP256R1())
    legit_public = ec.generate_private_key(ec.SECP256R1()).public_key()
    token = jwt.encode(_claims(), attacker, algorithm="ES256")

    class _Key:
        key = legit_public

    class _FakeJwks:
        def get_signing_key_from_jwt(self, _token):
            return _Key()

    monkeypatch.setattr(auth, "_jwks_client", lambda _url: _FakeJwks())
    with pytest.raises(jwt.PyJWTError):
        auth.verify_token(token, hs_settings)


def test_unsupported_algorithm_is_rejected(hs_settings):
    token = jwt.encode(_claims(), SECRET, algorithm="HS512")
    with pytest.raises(ValueError, match="unsupported"):
        auth.verify_token(token, hs_settings)


def test_service_role_token_is_rejected_even_if_signature_is_valid(hs_settings):
    """A service_role JWT signed with the project secret must never act as a user."""
    token = jwt.encode(_claims(role="service_role"), SECRET, algorithm="HS256")
    with pytest.raises(ValueError, match="role"):
        auth.verify_token(token, hs_settings)


def test_anon_role_token_is_rejected(hs_settings):
    token = jwt.encode(_claims(role="anon"), SECRET, algorithm="HS256")
    with pytest.raises(ValueError, match="role"):
        auth.verify_token(token, hs_settings)
