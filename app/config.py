"""Application settings, loaded from environment variables (and a local .env file).

Only PUBLIC values are ever exposed to the browser (see /api/config in main.py).
The Supabase service-role key is deliberately NOT a setting here: the API never holds it.
"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    supabase_url: str = ""
    supabase_anon_key: str = ""
    # Only needed for legacy Supabase projects that sign JWTs with HS256.
    supabase_jwt_secret: str | None = None

    app_env: str = "dev"
    models_dir: Path = Path("models")
    # Railway injects the deployed commit; used by /health to prove which build is live.
    railway_git_commit_sha: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
