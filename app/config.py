from functools import lru_cache
import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/auth/callback"
    secret_key: str = "change-me-in-production"
    allowed_domain: str = "hanyang.ac.kr"
    database_url: str = "sqlite+aiosqlite:///./rsv.db"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()
