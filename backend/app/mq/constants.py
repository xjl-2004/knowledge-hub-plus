"""RabbitMQ 交换机、队列与路由键。"""

RAG_REINDEX_EXCHANGE = "rag.reindex.exchange"
SEARCH_INDEX_EXCHANGE = "search.index.exchange"
KG_GRAPH_EXCHANGE = "kg.graph.exchange"

RAG_REINDEX_QUEUE = "kh.rag.reindex.queue"
SEARCH_INDEX_QUEUE = "kh.search.index.queue"
KG_GRAPH_QUEUE = "kh.kg.graph.queue"

RAG_RK_BY_IDS = "rag.reindex.by_ids"
RAG_RK_DELETE = "rag.reindex.delete"
SEARCH_RK_INDEX = "search.index.document"
SEARCH_RK_DELETE = "search.index.delete"
KG_RK_BUILD_BY_IDS = "kg.graph.build.by_ids"
KG_RK_DELETE = "kg.graph.delete"

TOPOLOGY: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (RAG_REINDEX_EXCHANGE, RAG_REINDEX_QUEUE, (RAG_RK_BY_IDS, RAG_RK_DELETE)),
    (
        SEARCH_INDEX_EXCHANGE,
        SEARCH_INDEX_QUEUE,
        (SEARCH_RK_INDEX, SEARCH_RK_DELETE),
    ),
    (KG_GRAPH_EXCHANGE, KG_GRAPH_QUEUE, (KG_RK_BUILD_BY_IDS, KG_RK_DELETE)),
)
