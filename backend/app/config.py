import re
from functools import lru_cache

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Aether"
    app_env: str = "development"
    app_debug: bool = True
    local_auth_mode: bool = True
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
    browser_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("AETHER_BROWSER_ENABLED", "BROWSER_ENABLED"),
    )
    browser_profile_dir: str = Field(
        default="~/.aether/browser-profile",
        validation_alias=AliasChoices("AETHER_BROWSER_PROFILE_DIR", "BROWSER_PROFILE_DIR"),
    )
    browser_allowed_hosts: str = Field(
        default="web.whatsapp.com,www.youtube.com,youtube.com,www.instagram.com,instagram.com",
        validation_alias=AliasChoices("AETHER_BROWSER_ALLOWED_HOSTS", "BROWSER_ALLOWED_HOSTS"),
    )
    browser_share_page_content_with_model: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "AETHER_BROWSER_SHARE_PAGE_CONTENT_WITH_MODEL",
            "BROWSER_SHARE_PAGE_CONTENT_WITH_MODEL",
        ),
    )
    browser_max_page_chars: int = Field(
        default=12000,
        validation_alias=AliasChoices("AETHER_BROWSER_MAX_PAGE_CHARS", "BROWSER_MAX_PAGE_CHARS"),
    )

    @field_validator("browser_allowed_hosts")
    @classmethod
    def normalize_browser_allowed_hosts(cls, value: str) -> str:
        hosts = [host.strip().lower().rstrip(".") for host in value.split(",") if host.strip()]
        if any(
            re.fullmatch(
                r"(?=.{1,253}\Z)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}",
                host,
            )
            is None
            for host in hosts
        ):
            raise ValueError("BROWSER_ALLOWED_HOSTS must contain exact hostnames separated by commas")
        return ",".join(dict.fromkeys(hosts))

    @field_validator("browser_max_page_chars")
    @classmethod
    def validate_browser_max_page_chars(cls, value: int) -> int:
        if not 1000 <= value <= 30000:
            raise ValueError("BROWSER_MAX_PAGE_CHARS must be between 1000 and 30000")
        return value

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
