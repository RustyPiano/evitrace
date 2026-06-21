from functools import lru_cache

from pydantic import Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    app_name: str = Field(default="EviTrace", validation_alias="APP_NAME")
    env: str = Field(default="development", validation_alias="ENV")
    secret_key: str = Field(default="change-me", validation_alias="SECRET_KEY")
    access_token_expire_hours: int = Field(
        default=8, validation_alias="ACCESS_TOKEN_EXPIRE_HOURS"
    )
    database_url: str = Field(
        default="sqlite:///./data/app.db", validation_alias="DATABASE_URL"
    )
    data_root: str = Field(default="./data", validation_alias="DATA_ROOT")
    max_upload_mb: int = Field(default=200, validation_alias="MAX_UPLOAD_MB")
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173"],
        validation_alias="CORS_ORIGINS",
    )
    local_llm_base_url: str = Field(
        default="http://host.docker.internal:11434/v1",
        validation_alias="LOCAL_LLM_BASE_URL",
    )
    local_llm_api_key: str = Field(default="local", validation_alias="LOCAL_LLM_API_KEY")
    local_llm_model: str = Field(default="qwen-local", validation_alias="LOCAL_LLM_MODEL")
    llm_timeout_sec: int = Field(default=180, validation_alias="LLM_TIMEOUT_SEC")
    llm_max_retries: int = Field(default=2, validation_alias="LLM_MAX_RETRIES")
    mock_ai: bool = Field(default=True, validation_alias="MOCK_AI")
    video_frame_interval_sec: int = Field(
        default=10, validation_alias="VIDEO_FRAME_INTERVAL_SEC"
    )
    time_conflict_minutes: int = Field(
        default=30, validation_alias="TIME_CONFLICT_MINUTES"
    )
    first_admin_username: str = Field(
        default="admin", validation_alias="FIRST_ADMIN_USERNAME"
    )
    first_admin_password: str = Field(
        default="admin123456", validation_alias="FIRST_ADMIN_PASSWORD"
    )

    @field_validator(
        "app_name",
        "env",
        "secret_key",
        "database_url",
        "data_root",
        "local_llm_base_url",
        "local_llm_api_key",
        "local_llm_model",
        "first_admin_username",
        "first_admin_password",
    )
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as exc:
        errors = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        )
        raise RuntimeError(f"Invalid application configuration: {errors}") from exc


settings = get_settings()
