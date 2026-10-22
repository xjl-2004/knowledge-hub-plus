"""管线内部流转的数据结构。"""

from dataclasses import dataclass, field


@dataclass
class DocumentChunk:
    """一篇文档切出来的一块文本。"""

    chunk_id: str
    document_id: str
    document_title: str
    content: str
    heading: str | None
    chunk_index: int
    total_chunks: int
    category_id: str | None = None
    author_id: str | None = None
    team_id: str | None = None
    is_public: bool = False
    doc_status: int | None = None
    publish_time: str | None = None
    embedding: list[float] = field(default_factory=list)


@dataclass
class ChunkHit:
    """kh_chunk 检索命中（关键词 / 向量 / RRF / 重排共用）。"""

    chunk_id: str
    document_id: str
    document_title: str
    content: str
    heading: str | None
    score: float
    bm25_score: float = 0.0
    vector_score: float = 0.0

    def to_dict(self) -> dict:
        return {
            "chunkId": self.chunk_id,
            "documentId": self.document_id,
            "documentTitle": self.document_title,
            "content": self.content,
            "heading": self.heading,
            "score": self.score,
            "bm25Score": self.bm25_score,
            "vectorScore": self.vector_score,
        }


@dataclass
class ExtractedEntity:
    name: str
    type: str
    description: str = ""
    aliases: list[str] = field(default_factory=list)


@dataclass
class ExtractedRelation:
    source: str
    target: str
    relation: str
    weight: float = 0.5


@dataclass
class ExtractionResult:
    chunk_id: str | None = None
    entities: list[ExtractedEntity] = field(default_factory=list)
    relations: list[ExtractedRelation] = field(default_factory=list)


@dataclass
class PipelineDocument:
    """Postgres 元数据 + Mongo 正文的合并快照。"""

    id: str
    title: str
    content: str
    summary: str | None = None
    category_id: str | None = None
    author_id: str | None = None
    team_id: str | None = None
    status: int = 0
    tags: str | None = None
    is_public: bool = False
    view_count: int = 0
    like_count: int = 0
    comment_count: int = 0
    publish_time: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
