"""Runtime settings, read from environment variables (documented in .env.example), and logging."""

import logging
import traceback
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
    ocr_lang: str = "pol+eng"
    ocr_min_chars: int = 25
    ocr_min_confidence: float = 60
    vision_fallback: bool = True
    max_text_chars: int = 2_000_000
    # 150,000 characters are about 50,000 tokens: far inside Haiku 5.5's 1M context and under the
    # 100,000-token prompt size past which its input costs 5x more. A dense 200-page document
    # (~820,000 characters) is 6 chunks, so with CHUNK_CONCURRENCY 8 its analysis takes one round
    # of parallel chunk calls plus the call that writes the summary.
    chunk_chars: int = 150_000

    # Per client IP; extract and analyze both count, so a file takes two. LLM spend is bounded by
    # daily_llm_call_limit, not by this limit, so it can let a person try several files a minute.
    rate_limit_per_minute: int = 20
    daily_llm_call_limit: int = 1000
    extraction_ttl_seconds: int = 900
    # DigitalOcean's edge ends every request at 100 s: both steps answer before it, with TIMEOUT
    # at the latest.
    extract_timeout_seconds: float = 85
    extract_memory_mb: int = 320
    analyze_timeout_seconds: float = 85

    @property
    def origins(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]

    @property
    def max_file_bytes(self) -> int:
        return self.max_file_mb * 1024 * 1024

    @property
    def max_ocr_bytes(self) -> int:
        """The browser's OCR part: at most max_text_chars characters, 4 bytes each in UTF-8."""
        return self.max_text_chars * 4


@lru_cache
def get_settings() -> Settings:
    return Settings()


def configure_logging() -> None:
    """Sizes, timings and codes only: no document text may reach the log."""
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)


def error_frames(error: BaseException) -> str:
    """File, line and code of every frame, without the message, which may quote the document."""
    return "".join(traceback.format_tb(error.__traceback__))
