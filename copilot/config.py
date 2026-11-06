from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="COPILOT_", env_file=".env", extra="ignore", populate_by_name=True
    )
    database_url: str = "sqlite:///./copilot.db"
    seed_demo: bool = True
    admin_token: str = Field(default="demo-admin-change-me", min_length=16)
    reader_token: str = Field(default="demo-reader-change-me", min_length=16)
    tenant: str = "acme"
    retrieval_backend: Literal["local", "opensearch", "gemini"] = "gemini"
    opensearch_url: str = "http://localhost:9200"
    opensearch_index: str = "copilot-chunks-v1"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"
    rerank: bool = False
    proposal_ttl_minutes: int = Field(default=60, ge=1, le=1440)
    generation_backend: Literal["extractive", "gemini"] = "gemini"
    gemini_api_key: SecretStr = Field(default=SecretStr(""), validation_alias="GEMINI_API_KEY")
    gemini_generation_model: str = Field(
        default="gemini-3.8-flash", validation_alias="GEMINI_GENERATION_MODEL", pattern=r"^[a-zA-Z0-9._-]+$"
    )
    gemini_embedding_model: str = Field(
        default="gemini-embedding-001",
        validation_alias="GEMINI_EMBEDDING_MODEL",
        pattern=r"^[a-zA-Z0-9._-]+$",
    )
    gemini_dimensions: int = Field(default=768, ge=128, le=3072)
    gemini_rewrite: bool = True
    gemini_rerank: bool = True
    input_usd_per_million: float | None = Field(default=None, ge=0)
    output_usd_per_million: float | None = Field(default=None, ge=0)
    embedding_usd_per_million: float | None = Field(default=None, ge=0)


@lru_cache
def get_settings() -> Settings:
    return Settings()
