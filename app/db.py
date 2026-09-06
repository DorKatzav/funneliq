"""Per-request Supabase client bound to the signed-in user's JWT.

Because every query carries the user's own token, Postgres applies the Row Level
Security policies in db/policies.sql. The API holds only the public anon key.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from supabase import Client, create_client
from supabase.lib.client_options import SyncClientOptions

from app.auth import UserContext, get_current_user
from app.config import Settings, get_settings


def get_user_client(
    user: UserContext = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
) -> Client:
    if not settings.supabase_url or not settings.supabase_anon_key:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Supabase is not configured on this server")
    client = create_client(
        settings.supabase_url,
        settings.supabase_anon_key,
        options=SyncClientOptions(auto_refresh_token=False, persist_session=False),
    )
    client.postgrest.auth(user.token)
    return client
