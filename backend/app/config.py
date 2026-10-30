from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Aether"
    app_env: str = "development"
    app_debug: bool = True
    database_url: str = "mysql+aiomysql://root:@localhost:3306/aether_db"
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    primary_model: str = "nvidia/nemotron-3-ultra-550b-a55b:free"
    coding_model: str = "cohere/north-mini-code:free"
    jwt_secret: str = "replace_with_a_long_random_secret"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    openrouter_timeout_seconds: float = 45
    openrouter_max_retries: int = 2
    frontend_url: str = "http://localhost:3000"
    cors_allowed_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    @field_validator("jwt_secret")
    @classmethod
    def validate_jwt_secret(cls, value: str) -> str:
        if (
            len(value) < 32
            or any(marker in value.lower() for marker in ("replace", "generate", "placeholder", "your_secret"))
        ):
            raise ValueError("JWT_SECRET must be a non-placeholder value of at least 32 characters")
        return value

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
