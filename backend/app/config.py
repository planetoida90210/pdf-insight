from functools import lru_cache
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    llm_provider: Literal["gemini", "anthropic"] = "gemini"
    llm_model: str | None = None
    gemini_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None

    allowed_origins: str = "https://planetoida90210.github.io"

    max_file_mb: int = 10
    max_pages: int = 200
    max_ocr_pages: int = 30
    ocr_lang: str = "pol+eng"
    ocr_min_chars: int = 25
    ocr_min_confidence: float = 60
    vision_fallback: bool = True
    chunk_chars: int = 40_000

    rate_limit_per_minute: int = 6
    daily_analysis_limit: int = 300
    extraction_ttl_seconds: int = 900
    llm_timeout_seconds: float = 60.0

    @property
    def origins(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]

    @property
    def max_file_bytes(self) -> int:
        return self.max_file_mb * 1024 * 1024

    @property
    def resolved_model(self) -> str:
        if self.llm_model:
            return self.llm_model
        # Defaults verified 2026-10-29 against provider docs (see app/llm.py).
        if self.llm_provider == "anthropic":
            return "claude-haiku-5-5"
        return "gemini-3.8-flash"


@lru_cache
def get_settings() -> Settings:
    return Settings()
