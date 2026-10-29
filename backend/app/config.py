"""Runtime settings, read from environment variables (documented in .env.example)."""

from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

LOG_FORMAT = "%(levelname)s %(name)s %(message)s"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openrouter_api_key: SecretStr | None = None
    llm_model: str = "anthropic/claude-haiku-5.5"
    llm_timeout_seconds: float = 60

    allowed_origins: str = "https://planetoida90210.github.io"

    max_file_mb: int = 10
    max_pages: int = 200
    max_ocr_pages: int = 30
    ocr_lang: str = "pol+eng"
    ocr_min_chars: int = 25
    ocr_min_confidence: float = 60
    vision_fallback: bool = True
    max_text_chars: int = 200_000
    chunk_chars: int = 40_000

    rate_limit_per_minute: int = 6
    daily_llm_call_limit: int = 1000
    extraction_ttl_seconds: int = 900
    extract_timeout_seconds: float = 90
    extract_memory_mb: int = 320
    analyze_timeout_seconds: float = 120

    @property
    def origins(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]

    @property
    def max_file_bytes(self) -> int:
        return self.max_file_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()
