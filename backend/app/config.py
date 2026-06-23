from functools import lru_cache
import sys
from pathlib import Path
from typing import Annotated

from pydantic import Field, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict, SettingsError
from sqlalchemy.engine import make_url


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WEAK_SECRET_KEYS = {"change-me", ""}
MIN_SECRET_KEY_LENGTH = 32
DEFAULT_FIRST_ADMIN_PASSWORD = "admin123456"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(PROJECT_ROOT / ".env",),
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
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"],
        validation_alias="CORS_ORIGINS",
    )
    local_llm_base_url: str = Field(
        default="http://host.docker.internal:11434/v1",
        validation_alias="LOCAL_LLM_BASE_URL",
    )
    local_llm_api_key: str = Field(default="local", validation_alias="LOCAL_LLM_API_KEY")
    local_llm_model: str = Field(default="qwen-local", validation_alias="LOCAL_LLM_MODEL")
    vlm_base_url: str | None = Field(default=None, validation_alias="VLM_BASE_URL")
    vlm_api_key: str | None = Field(default=None, validation_alias="VLM_API_KEY")
    vlm_model: str | None = Field(default=None, validation_alias="VLM_MODEL")
    llm_timeout_sec: int = Field(default=180, validation_alias="LLM_TIMEOUT_SEC")
    llm_max_retries: int = Field(default=2, validation_alias="LLM_MAX_RETRIES")
    extract_concurrency: int = Field(default=4, validation_alias="EXTRACT_CONCURRENCY")
    mock_ai: bool = Field(default=True, validation_alias="MOCK_AI")
    mock_llm: bool | None = Field(default=None, validation_alias="MOCK_LLM")
    mock_media: bool | None = Field(default=None, validation_alias="MOCK_MEDIA")
    mock_vision: bool | None = Field(default=None, validation_alias="MOCK_VISION")
    ocr_base_url: str | None = Field(default=None, validation_alias="OCR_BASE_URL")
    asr_base_url: str | None = Field(default=None, validation_alias="ASR_BASE_URL")
    ocr_model_dir: str | None = Field(default=None, validation_alias="OCR_MODEL_DIR")
    asr_model_dir: str | None = Field(default=None, validation_alias="ASR_MODEL_DIR")
    asr_model_size: str = Field(default="small", validation_alias="ASR_MODEL_SIZE")
    media_timeout_sec: int = Field(default=180, validation_alias="MEDIA_TIMEOUT_SEC")
    ffmpeg_timeout_sec: int = Field(default=120, validation_alias="FFMPEG_TIMEOUT_SEC")
    video_frame_interval_sec: int = Field(
        default=10, validation_alias="VIDEO_FRAME_INTERVAL_SEC"
    )
    time_conflict_minutes: int = Field(
        default=30, validation_alias="TIME_CONFLICT_MINUTES"
    )
    event_alias_path: str | None = Field(
        default=None, validation_alias="EVENT_ALIAS_PATH"
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
        "database_url",
        "data_root",
        "local_llm_base_url",
        "local_llm_api_key",
        "local_llm_model",
        "asr_model_size",
        "first_admin_username",
        "first_admin_password",
    )
    @classmethod
    def require_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value

    @field_validator("extract_concurrency")
    @classmethod
    def clamp_extract_concurrency(cls, value: int) -> int:
        return min(max(value, 1), 16)

    @field_validator(
        "ocr_base_url",
        "asr_base_url",
        "ocr_model_dir",
        "asr_model_dir",
        "event_alias_path",
        mode="before",
    )
    @classmethod
    def empty_media_setting_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("vlm_base_url", "vlm_api_key", "vlm_model", mode="before")
    @classmethod
    def empty_vlm_setting_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("mock_llm", "mock_media", "mock_vision", mode="before")
    @classmethod
    def empty_mock_override_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def validate_secrets_for_environment(self) -> "Settings":
        env = self.env.strip().lower()
        secret_key = self.secret_key.strip()
        weak_secret = (
            secret_key in WEAK_SECRET_KEYS
            or len(secret_key.encode("utf-8")) < MIN_SECRET_KEY_LENGTH
        )
        default_admin_password = self.first_admin_password == DEFAULT_FIRST_ADMIN_PASSWORD

        warnings: list[str] = []
        if weak_secret:
            message = (
                "SECRET_KEY is missing, default, or shorter than "
                f"{MIN_SECRET_KEY_LENGTH} bytes"
            )
            if env == "production":
                raise ValueError(message)
            warnings.append(message)
        if default_admin_password:
            message = "FIRST_ADMIN_PASSWORD is still the default admin123456"
            if env == "production":
                raise ValueError(message)
            warnings.append(message)

        if warnings and env == "development":
            print(
                "WARNING: insecure development configuration: " + "; ".join(warnings),
                file=sys.stderr,
            )
        return self

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @property
    def data_root_path(self) -> Path:
        data_root = Path(self.data_root).expanduser()
        if not data_root.is_absolute():
            data_root = PROJECT_ROOT / data_root
        return data_root.resolve()

    @property
    def effective_mock_llm(self) -> bool:
        return self.mock_ai if self.mock_llm is None else self.mock_llm

    @property
    def effective_mock_media(self) -> bool:
        return self.mock_ai if self.mock_media is None else self.mock_media

    @property
    def vlm_configured(self) -> bool:
        return bool(self.vlm_base_url and self.vlm_model and self.vlm_api_key)

    @property
    def effective_mock_vision(self) -> bool:
        if self.mock_vision is not None:
            return self.mock_vision
        return not self.vlm_configured

    @property
    def resolved_database_url(self) -> str:
        url = make_url(self.database_url)
        if not url.drivername.startswith("sqlite"):
            return self.database_url

        database = url.database
        if not database or database == ":memory:":
            return self.database_url

        database_path = Path(database).expanduser()
        if not database_path.is_absolute():
            database_path = PROJECT_ROOT / database_path
        return url.set(database=str(database_path.resolve())).render_as_string(
            hide_password=False
        )


@lru_cache
def get_settings() -> Settings:
    try:
        return Settings()
    except (ValidationError, SettingsError) as exc:
        if isinstance(exc, ValidationError):
            errors = "; ".join(
                f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
                for error in exc.errors()
            )
        else:
            errors = str(exc)
        raise RuntimeError(f"Invalid application configuration: {errors}") from exc


settings = get_settings()
