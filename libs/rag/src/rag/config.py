"""RAG settings: Qdrant vectors + Neon registry/cache. Depends only on types."""

from functools import lru_cache

from pydantic_settings import BaseSettings


class RagSettings(BaseSettings):
    qdrant_url: str = ""
    qdrant_api_key: str = ""
    qdrant_collection: str = "chunks"
    agentic_assistant_database_url: str = ""
    openai_api_key: str = ""
    openai_base_url: str = ""
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    reranker_backend: str = "none"
    reranker_top_n: int = 20
    cache_ttl_hours: int = 24
    cache_semantic_threshold: float = 0.92
    chunk_size: int = 900
    chunk_overlap: int = 150
    openai_retry_attempts: int = 3
    openai_retry_min_wait: float = 1.0
    openai_retry_max_wait: float = 10.0

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


@lru_cache
def get_rag_settings() -> RagSettings:
    return RagSettings()
