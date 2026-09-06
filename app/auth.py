"""Supabase JWT verification.

The browser signs in with Supabase Auth and sends `Authorization: Bearer <access_token>`.
We verify the token's signature locally:

* ES256 / RS256 (current Supabase projects): public keys fetched from the project's JWKS
  endpoint and cached by PyJWT.
* HS256 (legacy projects): the shared secret from SUPABASE_JWT_SECRET.

Any failure -> 401. The verified token is kept on the UserContext so app/db.py can
forward it to Supabase and let Row Level Security do its job.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from app.config import Settings, get_settings

ASYMMETRIC_ALGS = ("ES256", "RS256")
SYMMETRIC_ALGS = ("HS256",)
AUDIENCE = "authenticated"

_bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class UserContext:
    user_id: str
    email: str | None
    token: str


@lru_cache(maxsize=4)
def _jwks_client(supabase_url: str) -> PyJWKClient:
    return PyJWKClient(f"{supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json", cache_keys=True)


def _signing_key(token: str, alg: str, settings: Settings):
    """Return the key PyJWT should verify `token` with, based on its declared algorithm."""
    if alg in ASYMMETRIC_ALGS:
        if not settings.supabase_url:
            raise ValueError("SUPABASE_URL is not configured")
        return _jwks_client(settings.supabase_url).get_signing_key_from_jwt(token).key
    if alg in SYMMETRIC_ALGS:
        if not settings.supabase_jwt_secret:
            raise ValueError("token uses HS256 but SUPABASE_JWT_SECRET is not configured")
        return settings.supabase_jwt_secret
    raise ValueError(f"unsupported JWT algorithm: {alg}")


def verify_token(token: str, settings: Settings) -> dict:
    """Decode and verify a Supabase access token. Raises jwt.PyJWTError / ValueError on failure."""
    alg = jwt.get_unverified_header(token).get("alg", "")
    key = _signing_key(token, alg, settings)
    claims = jwt.decode(token, key, algorithms=[alg], audience=AUDIENCE, options={"require": ["exp", "sub"]})
    if claims.get("role") != "authenticated":
        raise ValueError(f"token role is not 'authenticated' (got {claims.get('role')!r})")
    return claims


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    settings: Settings = Depends(get_settings),
) -> UserContext:
    if creds is None or creds.scheme.lower() != "bearer" or not creds.credentials:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, "missing bearer token", {"WWW-Authenticate": "Bearer"}
        )
    token = creds.credentials
    try:
        claims = verify_token(token, settings)
    except (jwt.PyJWTError, ValueError) as exc:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, f"invalid token: {exc}", {"WWW-Authenticate": "Bearer"}
        ) from exc
    return UserContext(user_id=str(claims["sub"]), email=claims.get("email"), token=token)
