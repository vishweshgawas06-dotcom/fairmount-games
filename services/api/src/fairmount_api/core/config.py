"""Environment-driven configuration with fail-fast validation."""

from __future__ import annotations

from functools import lru_cache

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_PLACEHOLDER_PREFIX = "replace-with"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    app_name: str = "FairMount Games"
    database_url: str = "postgresql+psycopg://fairmount:change-me@localhost:5432/fairmount"
    app_secret_key: str = "replace-with-a-random-local-development-secret"

    @field_validator("app_env")
    @classmethod
    def _known_env(cls, value: str) -> str:
        if value not in {"development", "test", "staging", "production"}:
            raise ValueError("APP_ENV must be development, test, staging or production")
        return value

    @model_validator(mode="after")
    def _no_placeholder_secrets_outside_dev(self) -> Settings:
        if self.app_env in {"staging", "production"}:
            if self.app_secret_key.startswith(_PLACEHOLDER_PREFIX):
                raise ValueError("APP_SECRET_KEY must be a real secret in staging/production")
            if len(self.app_secret_key) < 32:
                raise ValueError("APP_SECRET_KEY must be at least 32 characters")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
