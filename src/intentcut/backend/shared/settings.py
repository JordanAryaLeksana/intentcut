"""Environment configuration and explicit resource budgets for the local backend."""

from pathlib import Path

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class BackendSettings(BaseSettings):
    """Load secrets from the environment; tests can pass every value explicitly."""

    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", frozen=True, hide_input_in_errors=True
    )

    database_url: SecretStr
    cors_origins: list[str] = Field(default_factory=list)
    media_root: Path = Path(".local/media")
    ai_jobs_local_enabled: bool = False
    ai_jobs_local_enabled: bool = False
    ai_jobs_browser_enabled: bool = False
    ai_processing_enabled: bool = False
    image_generation_enabled: bool = False
    image_max_jobs_per_project: int = Field(default=3, ge=1, le=20)
    image_timeout_seconds: float = Field(default=240, ge=1, le=600)
    voice_transcription_enabled: bool = False
    voice_max_duration_seconds: int = Field(default=120, ge=1, le=600)
    voice_max_jobs_per_project: int = Field(default=3, ge=1, le=20)
    voice_timeout_seconds: float = Field(default=180, ge=1, le=600)
    model_api_key: SecretStr | None = None
    ai_max_media: int = Field(default=4, ge=1, le=10)
    ai_max_windows: int = Field(default=12, ge=1, le=12)
    ai_max_source_bytes: int = Field(default=512 * 1024 * 1024, gt=0)
    ai_max_remote_file_bytes: int = Field(
        default=25 * 1024 * 1024, gt=0, le=25 * 1024 * 1024
    )
    ai_max_remote_total_bytes: int = Field(default=100 * 1024 * 1024, gt=0)
    ai_max_inference_requests: int = Field(default=13, ge=2, le=13)
    max_upload_files: int = Field(default=10, ge=1, le=10)
    max_file_bytes: int = Field(default=128 * 1024 * 1024, gt=0)
    max_request_bytes: int = Field(default=512 * 1024 * 1024, gt=0)
    copy_chunk_bytes: int = Field(default=1024 * 1024, gt=0, le=1024 * 1024)

    @field_validator("database_url")
    @classmethod
    def require_postgresql(cls, value: SecretStr) -> SecretStr:
        try:
            url = make_url(value.get_secret_value())
            valid = url.drivername == "postgresql+psycopg" and bool(url.database)
        except Exception:
            valid = False
        if not valid:
            raise ValueError(
                "DATABASE_URL must use postgresql+psycopg and name a database"
            )
        return value

    @field_validator("media_root")
    @classmethod
    def absolute_root(cls, value: Path) -> Path:
        return value.expanduser().absolute()

    @model_validator(mode="after")
    def validate_budgets(self) -> "BackendSettings":
        if self.max_file_bytes > self.max_request_bytes:
            raise ValueError("max_file_bytes must not exceed max_request_bytes")
        return self
