from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Knowledge Hub Plus"
    app_public_url: str = "http://localhost:3000"
    port: int = 3000
    debug: bool = False
    api_prefix: str = ""

    # PostgreSQL
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "user"
    postgres_password: str = "123456"
    postgres_db: str = "knowledge_hub"

    # MongoDB
    mongo_uri: str = (
        "mongodb://mongo_user:mongo_pass123@localhost:27017/"
        "knowledge_hub?authSource=admin"
    )
    mongo_db: str = "knowledge_hub"

    # Snowflake
    snowflake_worker_id: int = 1
    snowflake_offset: int = 1704067200000

    # Object storage
    rustfs_enabled: bool = True
    rustfs_endpoint: str = "http://localhost:9000"
    rustfs_public_url: str = "http://localhost:9000"
    rustfs_access_key: str = "rustfsadmin"
    rustfs_secret_key: str = "rustfsadmin"
    rustfs_bucket: str = "knowledge-hub"
    rustfs_region: str = "us-east-1"

    # RabbitMQ
    rabbitmq_enabled: bool = True
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672"

    # RAG chunking
    rag_chunk_size: int = 512
    rag_chunk_overlap: int = 64

    # Embedding
    embedding_dimension: int = 1024
    embedding_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    embedding_model: str = "text-embedding-v3"
    embedding_batch_size: int = 10
    embedding_api_key: str | None = None
    dashscope_api_key: str | None = None

    # Hybrid retrieval
    rag_hybrid_top_k: int = 20
    rag_rrf_c: int = 60
    rag_rerank_enabled: bool = True
    rag_rerank_model: str = "qwen3-rerank"
    rag_min_score: float = 0.4
    rerank_api_key: str | None = None
    rerank_base_url: str = "https://dashscope.aliyuncs.com"

    # LLM
    kg_llm_timeout_ms: int = 120000
    kg_max_entities: int = 12
    kg_max_relations: int = 15
    ai_chat_timeout_ms: int = 60000
    ai_query_rewrite_timeout_ms: int = 15000
    openai_api_key: str | None = None
    llm_api_key: str | None = None
    openai_base_url: str | None = None
    llm_base_url: str | None = None
    model_name: str | None = None
    llm_model: str | None = None
    llm_enable_thinking: bool = False

    # Web search
    bocha_api_key: str | None = None

    # Elasticsearch
    elasticsearch_enabled: bool = True
    elasticsearch_node: str = "http://localhost:9200"

    # Neo4j
    neo4j_enabled: bool = True
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "12345678"

    # JWT
    jwt_secret: str = "dev-secret-change-me-in-production"
    jwt_access_expires: str = "2h"
    jwt_refresh_expires: str = "7d"

    # Email verification
    require_email_verification: bool = False

    # SMTP
    mail_host: str | None = None
    mail_port: int = 587
    mail_secure: bool = False
    mail_user: str | None = None
    mail_pass: str | None = None
    mail_from: str = "Knowledge Hub <noreply@example.com>"

    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: str | None = None
    redis_db: int = 0

    # Chat memory
    chat_short_memory_ttl_seconds: int = 86400
    chat_short_memory_max_messages: int = 20
    chat_short_memory_key_prefix: str = "kh:chat"

    # Long memory
    mem0_api_key: str | None = None
    mem0_host: str = "https://api.mem0.ai"
    mem0_top_k: int = 5

    # Document review
    document_require_approval: bool = True

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def llm_key(self) -> str:
        return self.openai_api_key or self.llm_api_key or self.dashscope_api_key or ""

    @property
    def llm_base(self) -> str:
        return (
            self.openai_base_url
            or self.llm_base_url
            or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        )

    @property
    def llm_model_name(self) -> str:
        return self.model_name or self.llm_model or "qwen-plus"

    @property
    def embedding_key(self) -> str:
        return self.embedding_api_key or self.dashscope_api_key or self.openai_api_key or ""

    @property
    def rerank_key(self) -> str:
        return self.rerank_api_key or self.dashscope_api_key or self.openai_api_key or ""


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
