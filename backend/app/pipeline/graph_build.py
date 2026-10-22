"""知识图谱构建与检索（Neo4j）。

图模型：
  (KnowledgeDocument)-[:HAS_CHUNK]->(DocumentChunk)
  (DocumentChunk)-[:MENTIONS]->(KnowledgeEntity)
  (KnowledgeEntity)-[:RELATED_TO]->(KnowledgeEntity)
"""

import logging
from datetime import datetime
from typing import Any

from neo4j import AsyncSession

from app.db import neo4j as neo4j_db
from app.pipeline import chunking, extraction
from app.pipeline.types import (
    DocumentChunk,
    ExtractionResult,
    PipelineDocument,
)
from app.pipeline.visibility import neo4j_access_params, neo4j_document_access_where

logger = logging.getLogger(__name__)


def _to_iso(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    try:
        return datetime.fromisoformat(str(value)).isoformat()
    except ValueError:
        return str(value)


async def build_for_document(doc: PipelineDocument) -> int:
    """单篇文档全量重建图谱：先清旧，再建图。"""
    driver = neo4j_db.get_driver()
    if driver is None:
        logger.warning("跳过 KG 构建（Neo4j 不可用）：documentId=%s", doc.id)
        return 0
    if not doc.content.strip():
        logger.warning("文档内容为空，跳过 KG：documentId=%s", doc.id)
        return 0

    await delete_for_document(doc.id)

    total_entities = 0
    now = datetime.now().isoformat()

    async with driver.session() as session:
        # ① 创建文档节点，幂等合并
        await _merge_document_node(session, doc, now)

        # ② 复用 RAG 分块
        chunks = await chunking.chunk(
            content=doc.content,
            document_id=doc.id,
            document_title=doc.title,
            category_id=doc.category_id,
            author_id=doc.author_id,
            team_id=doc.team_id,
            is_public=doc.is_public,
            doc_status=doc.status,
            publish_time=_to_iso(doc.publish_time),
        )

        for chunk in chunks:
            # ③ chunk 节点 + HAS_CHUNK 边
            await _merge_chunk_node(session, doc.id, chunk, now)

            # ④ 抽取实体关系，写入图
            try:
                extracted = await extraction.extract(
                    chunk.content,
                    chunk.heading,
                    doc.title,
                )
                extracted.chunk_id = chunk.chunk_id
                count = await _write_extraction(session, extracted, now)
                total_entities += count
            except Exception as exc:
                logger.error(
                    "KG 抽取失败，跳过该块：documentId=%s, chunk=%s, %s",
                    doc.id,
                    chunk.chunk_index,
                    exc,
                )

        logger.info(
            "KG 图谱构建完成：documentId=%s, chunks=%s, entities=%s",
            doc.id,
            len(chunks),
            total_entities,
        )
        return total_entities


async def build_batch(docs: list[PipelineDocument]) -> None:
    """批量建图，单篇失败只记日志不阻断。"""
    for doc in docs:
        try:
            await build_for_document(doc)
        except Exception as exc:
            logger.error("KG 构建失败：documentId=%s, %s", doc.id, exc)


async def delete_for_document(document_id: str) -> None:
    """删除文档及其 chunk，并清理无引用实体（孤儿）。"""
    driver = neo4j_db.get_driver()
    if driver is None:
        return

    async with driver.session() as session:
        # 删文档和所有 chunk，DETACH 同时拆边
        await session.run(
            """
            MATCH (d:KnowledgeDocument {id: $id})
            OPTIONAL MATCH (d)-[:HAS_CHUNK]->(c:DocumentChunk)
            DETACH DELETE c, d
            """,
            {"id": document_id},
        )
        # 清理无人提及的实体
        await session.run(
            """
            MATCH (e:KnowledgeEntity)
            WHERE NOT (e)<-[:MENTIONS]-()
            DETACH DELETE e
            """
        )

    logger.info("KG 图谱已删除：documentId=%s", document_id)


async def update_visibility(
    document_id: str,
    visibility: dict[str, Any],
) -> None:
    """只更新文档节点可见性字段，不必抽实体重跑。"""
    driver = neo4j_db.get_driver()
    if driver is None:
        logger.warning(
            "跳过图谱可见性更新（Neo4j 不可用）：documentId=%s", document_id
        )
        return

    now = datetime.now().isoformat()
    async with driver.session() as session:
        await session.run(
            """
            MATCH (d:KnowledgeDocument {id: $id})
            SET d.isPublic = $isPublic, d.teamId = $teamId, d.authorId = $authorId,
                  d.updatedAt = $now
            """,
            {
                "id": document_id,
                "isPublic": visibility.get("isPublic"),
                "teamId": visibility.get("teamId"),
                "authorId": visibility.get("authorId"),
                "now": now,
            },
        )

    logger.info("图谱可见性已更新：documentId=%s", document_id)


async def list_nodes(
    type: str | None = None, limit: int = 200, scope: Any = None
) -> list[dict[str, Any]]:
    """列出知识实体节点。"""
    driver = neo4j_db.get_driver()
    if driver is None:
        logger.warning("跳过图谱节点查询（Neo4j 不可用）")
        return []

    cap = min(max(limit, 1), 500)
    params = {
        "type": type if type and type.strip() else None,
        "limit": cap,
        **neo4j_access_params(scope),
    }

    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (e:KnowledgeEntity)
            WHERE ($type IS NULL OR $type = '' OR e.type = $type)
              AND (
                $unrestricted OR EXISTS {
                  MATCH (d:KnowledgeDocument)-[:HAS_CHUNK]->(:DocumentChunk)-[:MENTIONS]->(e)
                  WHERE """
            + neo4j_document_access_where("d")
            + """
                }
              )
            RETURN DISTINCT e.name AS id, e.name AS name, e.type AS type,
                   e.description AS description
            LIMIT $limit
            """,
            params,
        )
        return [
            {
                "id": record["id"],
                "name": record["name"],
                "type": record["type"],
                "description": record["description"],
            }
            for record in await result.data()
        ]


async def list_edges(
    limit: int = 500, scope: Any = None
) -> list[dict[str, Any]]:
    """列出实体间 RELATED_TO 边。"""
    driver = neo4j_db.get_driver()
    if driver is None:
        logger.warning("跳过图谱边查询（Neo4j 不可用）")
        return []

    cap = min(max(limit, 1), 1000)
    params = {"limit": cap, **neo4j_access_params(scope)}

    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (a:KnowledgeEntity)-[r:RELATED_TO]->(b:KnowledgeEntity)
            WHERE $unrestricted OR (
              EXISTS {
                MATCH (d1:KnowledgeDocument)-[:HAS_CHUNK]->(:DocumentChunk)-[:MENTIONS]->(a)
                WHERE """
            + neo4j_document_access_where("d1")
            + """
              }
              AND EXISTS {
                MATCH (d2:KnowledgeDocument)-[:HAS_CHUNK]->(:DocumentChunk)-[:MENTIONS]->(b)
                WHERE """
            + neo4j_document_access_where("d2")
            + """
              }
            )
            RETURN a.name AS source, b.name AS target,
                   r.relation AS relation, r.weight AS weight
            LIMIT $limit
            """,
            params,
        )
        return [
            {
                "source": record["source"],
                "target": record["target"],
                "relation": record["relation"] or "RELATED_TO",
                "weight": (
                    float(record["weight"])
                    if isinstance(record["weight"], (int, float))
                    else 0.5
                ),
            }
            for record in await result.data()
        ]


async def search_graph(
    keyword: str, limit: int = 50, scope: Any = None
) -> list[dict[str, Any]]:
    """关键词命中实体 / 文档 / 块。"""
    driver = neo4j_db.get_driver()
    if driver is None:
        logger.warning("跳过图谱检索（Neo4j 不可用）")
        return []

    kw = keyword.strip()
    if not kw:
        return []

    cap = min(max(limit, 1), 200)
    params = {"kw": kw, "limit": cap, **neo4j_access_params(scope)}

    async with driver.session() as session:
        result = await session.run(
            """
            MATCH (n)
            WHERE (
                 toLower(coalesce(n.name, '')) CONTAINS toLower($kw)
              OR toLower(coalesce(n.title, '')) CONTAINS toLower($kw)
              OR toLower(coalesce(n.heading, '')) CONTAINS toLower($kw)
              OR toLower(coalesce(n.description, '')) CONTAINS toLower($kw)
              OR toLower(coalesce(n.summary, '')) CONTAINS toLower($kw)
              OR toLower(coalesce(n.content, '')) CONTAINS toLower($kw)
            )
            AND (
              $unrestricted
              OR (n:KnowledgeDocument AND """
            + neo4j_document_access_where("n")
            + """)
              OR (n:DocumentChunk AND EXISTS {
                MATCH (d:KnowledgeDocument)-[:HAS_CHUNK]->(n)
                WHERE """
            + neo4j_document_access_where("d")
            + """
              })
              OR (n:KnowledgeEntity AND EXISTS {
                MATCH (d:KnowledgeDocument)-[:HAS_CHUNK]->(:DocumentChunk)-[:MENTIONS]->(n)
                WHERE """
            + neo4j_document_access_where("d")
            + """
              })
            )
            RETURN labels(n)[0] AS label,
                   coalesce(n.name, n.title, n.heading, n.id, n.chunkId) AS name,
                   coalesce(n.id, n.chunkId, n.name) AS id,
                   n.type AS type,
                   n.title AS title,
                   n.description AS description,
                   n.heading AS heading,
                   n.documentId AS documentId,
                   n.summary AS summary,
                   CASE
                     WHEN n.content IS NULL THEN null
                     ELSE substring(n.content, 0, 160)
                   END AS snippet
            ORDER BY label, name
            LIMIT $limit
            """,
            params,
        )
        return [
            {
                "id": record["id"],
                "name": record["name"],
                "label": record["label"],
                "type": record["type"],
                "title": record["title"],
                "description": record["description"],
                "heading": record["heading"],
                "documentId": record["documentId"],
                "summary": record["summary"],
                "snippet": record["snippet"],
            }
            for record in await result.data()
        ]


async def get_overview(
    params: dict[str, Any], scope: Any = None
) -> dict[str, Any]:
    """全景图查询（供前端力导向图渲染）。"""
    empty = {
        "nodes": [],
        "edges": [],
        "stats": {
            "nodeCount": 0,
            "edgeCount": 0,
            "documentCount": 0,
            "entityCount": 0,
            "tagCount": 0,
            "mentionCount": 0,
            "relatedCount": 0,
            "entityTypes": [],
        },
        "topEntities": [],
        "recentNodes": [],
        "entityTypes": [],
    }

    driver = neo4j_db.get_driver()
    if driver is None:
        logger.warning("跳过图谱全景（Neo4j 不可用）")
        return empty

    kw = (params.get("keyword") or "").strip()
    entity_type = (params.get("entity_type") or "").strip() or None
    from_iso = (params.get("from") or "").strip() or None
    to_iso = (params.get("to") or "").strip() or None
    doc_limit = min(max(params.get("doc_limit") or 24, 1), 80)
    vis = neo4j_access_params(scope)

    async with driver.session() as session:
        # 统计当前可见范围
        stats_result = await session.run(
            """
            OPTIONAL MATCH (d:KnowledgeDocument)
            WHERE """
            + neo4j_document_access_where("d")
            + """
            WITH count(d) AS documentCount
            OPTIONAL MATCH (d)-[:HAS_CHUNK]->(:DocumentChunk)-[:MENTIONS]->(e:KnowledgeEntity)
            WHERE """
            + neo4j_document_access_where("d")
            + """
            WITH documentCount, count(DISTINCT e) AS entityCount
            OPTIONAL MATCH (e1:KnowledgeEntity)-[r:RELATED_TO]->(e2:KnowledgeEntity)
            WHERE $unrestricted OR (
              EXISTS {
                MATCH (d:KnowledgeDocument)-[:HAS_CHUNK]->(:DocumentChunk)-[:MENTIONS]->(e1)
                WHERE """
            + neo4j_document_access_where("d")
            + """
              }
              AND EXISTS {
                MATCH (d:KnowledgeDocument)-[:HAS_CHUNK]->(:DocumentChunk)-[:MENTIONS]->(e2)
                WHERE """
            + neo4j_document_access_where("d")
            + """
              }
            )
            WITH documentCount, entityCount, count(r) AS relatedCount
            OPTIONAL MATCH (d3:KnowledgeDocument)-[:HAS_CHUNK]->(:DocumentChunk)-[:MENTIONS]->(e3:KnowledgeEntity)
            WHERE """
            + neo4j_document_access_where("d3")
            + """
            RETURN documentCount, entityCount, relatedCount, count(e3) AS mentionCount
            """,
            vis,
        )
        stats_row = await stats_result.single()
        stats = {
            "nodeCount": 0,
            "edgeCount": 0,
            "documentCount": (
                int(stats_row["documentCount"]) if stats_row else 0
            ),
            "entityCount": (
                int(stats_row["entityCount"]) if stats_row else 0
            ),
            "tagCount": 0,
            "mentionCount": (
                int(stats_row["mentionCount"]) if stats_row else 0
            ),
            "relatedCount": (
                int(stats_row["relatedCount"]) if stats_row else 0
            ),
            "entityTypes": [],
        }

        # 按类型分组统计
        if stats["entityCount"] > 0:
            type_result = await session.run(
                """
                MATCH (d:KnowledgeDocument)-[:HAS_CHUNK]->(:DocumentChunk)-[:MENTIONS]->(e:KnowledgeEntity)
                WHERE """
                + neo4j_document_access_where("d")
                + """ AND e.type IS NOT NULL AND e.type <> ''
                RETURN e.type AS type, count(DISTINCT e) AS count
                ORDER BY count DESC
                """,
                vis,
            )
            stats["entityTypes"] = [
                {"type": r["type"], "count": int(r["count"])}
                for r in await type_result.data()
            ]

        # 提及最多的 top5 实体
        top_result = await session.run(
            """
            MATCH (e:KnowledgeEntity)<-[:MENTIONS]-(:DocumentChunk)<-[:HAS_CHUNK]-(d)
            WHERE """
            + neo4j_document_access_where("d")
            + """
            RETURN e.name AS name, e.type AS type, count(*) AS degree
            ORDER BY degree DESC
            LIMIT 5
            """,
            vis,
        )
        top_entities = [
            {
                "name": r["name"],
                "type": r["type"],
                "degree": int(r["degree"]),
            }
            for r in await top_result.data()
        ]

        # 最近更新的 8 篇文档（不受时间过滤）
        recent_result = await session.run(
            """
            MATCH (d:KnowledgeDocument)
            WHERE """
            + neo4j_document_access_where("d")
            + """
            RETURN d.id AS id, d.title AS name, d.updatedAt AS updatedAt
            ORDER BY d.updatedAt DESC
            LIMIT 8
            """,
            vis,
        )
        recent_nodes = [
            {
                "id": f"doc:{record['id']}",
                "name": str(record["name"]),
                "kind": "document",
                "updatedAt": record["updatedAt"],
            }
            for record in await recent_result.data()
        ]

        # 主文档查询
        cypher = (
            """
            MATCH (d:KnowledgeDocument)
            WHERE """
            + neo4j_document_access_where("d")
            + """
              AND ($kw = '' OR toLower(coalesce(d.title, '')) CONTAINS toLower($kw)
                   OR toLower(coalesce(d.summary, '')) CONTAINS toLower($kw)
                   OR toLower(coalesce(d.tags, '')) CONTAINS toLower($kw))
              AND ($from IS NULL OR d.updatedAt >= $from)
              AND ($to IS NULL OR d.updatedAt <= $to)
            WITH d ORDER BY d.updatedAt DESC LIMIT $docLimit
            OPTIONAL MATCH (d)-[:HAS_CHUNK]->(:DocumentChunk)-[:MENTIONS]->(e:KnowledgeEntity)
            WHERE ($entityType IS NULL OR e.type = $entityType)
            RETURN d.id AS docId, d.title AS docTitle, d.summary AS docSummary,
                   d.tags AS docTags, d.updatedAt AS docUpdatedAt,
                   collect(DISTINCT CASE WHEN e IS NULL THEN NULL ELSE {
                     name: e.name, type: e.type, description: e.description
                   } END) AS entities
            """
        )
        result = await session.run(
            cypher,
            {
                "kw": kw,
                "entityType": entity_type,
                "from": from_iso,
                "to": to_iso,
                "docLimit": doc_limit,
                **vis,
            },
        )

        nodes: dict[str, dict[str, Any]] = {}
        edges: dict[str, dict[str, Any]] = {}

        def add_node(
            node_id: str,
            name: str,
            kind: str,
            **kwargs: Any,
        ) -> None:
            if node_id not in nodes:
                nodes[node_id] = {
                    "id": node_id,
                    "name": name,
                    "kind": kind,
                    **kwargs,
                }

        def add_edge(
            source: str,
            target: str,
            relation: str,
            kind: str,
        ) -> None:
            key = f"{kind}|{source}|{target}|{relation}"
            if key not in edges:
                edges[key] = {
                    "source": source,
                    "target": target,
                    "relation": relation,
                    "kind": kind,
                }

        def split_tags(raw: Any) -> list[str]:
            return [
                t.strip()
                for t in str(raw or "").replace("，", ",").split(",")
                if t.strip()
            ]

        doc_records = list(await result.data())

        # 关键词命中实体但标题未命中时，把提及该实体的文档补进来
        if kw:
            extra = await session.run(
                """
                MATCH (e:KnowledgeEntity)<-[:MENTIONS]-(:DocumentChunk)<-[:HAS_CHUNK]-(d:KnowledgeDocument)
                WHERE """
                + neo4j_document_access_where("d")
                + """
                  AND (toLower(coalesce(e.name, '')) CONTAINS toLower($kw)
                   OR toLower(coalesce(e.description, '')) CONTAINS toLower($kw))
                WITH DISTINCT d
                WHERE ($from IS NULL OR d.updatedAt >= $from)
                  AND ($to IS NULL OR d.updatedAt <= $to)
                OPTIONAL MATCH (d)-[:HAS_CHUNK]->(:DocumentChunk)-[:MENTIONS]->(e2:KnowledgeEntity)
                WHERE $entityType IS NULL OR e2.type = $entityType
                RETURN d.id AS docId, d.title AS docTitle, d.summary AS docSummary,
                       d.tags AS docTags, d.updatedAt AS docUpdatedAt,
                       collect(DISTINCT CASE WHEN e2 IS NULL THEN NULL ELSE {
                         name: e2.name, type: e2.type, description: e2.description
                       } END) AS entities
                LIMIT $docLimit
                """,
                {
                    "kw": kw,
                    "entityType": entity_type,
                    "from": from_iso,
                    "to": to_iso,
                    "docLimit": doc_limit,
                    **vis,
                },
            )
            seen_doc_ids = {str(record["docId"]) for record in doc_records}
            for record in await extra.data():
                if str(record["docId"]) in seen_doc_ids:
                    continue
                doc_records.append(record)
        for record in doc_records:
            doc_id = str(record["docId"])
            doc_node_id = f"doc:{doc_id}"
            add_node(
                doc_node_id,
                name=str(record["docTitle"] or ""),
                kind="document",
                type="DOCUMENT",
                documentId=doc_id,
                description=record["docSummary"],
                updatedAt=record["docUpdatedAt"],
            )
            for tag in split_tags(record["docTags"]):
                if not tag:
                    continue
                tag_id = f"tag:{tag}"
                add_node(tag_id, name=tag, kind="tag", type="TAG")
                add_edge(doc_node_id, tag_id, "标注", "tagged")

            for entity in (record["entities"] or []):
                if not entity or not entity.get("name"):
                    continue
                entity_name = entity["name"]
                entity_id = f"entity:{entity_name}"
                add_node(
                    entity_id,
                    name=entity_name,
                    kind="entity",
                    type=entity.get("type") or "CONCEPT",
                    description=entity.get("description"),
                )
                add_edge(doc_node_id, entity_id, "提及", "mentions")

        # 补全当前画布上实体之间的关系
        entity_names = [
            n["name"]
            for n in nodes.values()
            if n["kind"] == "entity"
        ]
        if len(entity_names) >= 2:
            rel_result = await session.run(
                """
                MATCH (a:KnowledgeEntity)-[r:RELATED_TO]->(b:KnowledgeEntity)
                WHERE a.name IN $names AND b.name IN $names
                RETURN a.name AS source,
                       coalesce(r.relation, 'RELATED_TO') AS relation,
                       b.name AS target
                LIMIT 400
                """,
                {"names": entity_names},
            )
            for record in await rel_result.data():
                source_id = f"entity:{record['source']}"
                target_id = f"entity:{record['target']}"
                add_edge(
                    source_id, target_id, record["relation"] or "关联", "related"
                )

        stats["nodeCount"] = len(nodes)
        stats["edgeCount"] = len(edges)
        stats["tagCount"] = sum(
            1 for node in nodes.values() if node["kind"] == "tag"
        )

        return {
            "nodes": list(nodes.values()),
            "edges": list(edges.values()),
            "stats": stats,
            "topEntities": top_entities,
            "recentNodes": recent_nodes,
            "entityTypes": stats["entityTypes"],
        }


def split_graph_keywords(keyword: str | list[str]) -> list[str]:
    """把「发票 报销」这类组合关键词拆成可匹配的短实体名。"""
    parts = keyword if isinstance(keyword, list) else [keyword]
    seen: set[str] = set()
    keywords: list[str] = []
    for part in parts:
        for raw in str(part).replace("/", " ").split():
            word = raw.strip()
            if not word:
                continue
            key = word.lower()
            if key in seen:
                continue
            seen.add(key)
            keywords.append(word)
    return keywords


async def retrieve_for_chat(
    keyword: str | list[str], limit: int = 8, scope: Any = None
) -> dict[str, Any]:
    """按短实体名找可见实体，再取实体间关系与来源文档。"""
    keywords = split_graph_keywords(keyword)
    empty = {
        "query": " / ".join(keywords),
        "entities": [],
        "relations": [],
        "documents": [],
    }
    if not keywords:
        return empty

    driver = neo4j_db.get_driver()
    if driver is None:
        logger.warning("跳过图谱对话检索（Neo4j 不可用）")
        return empty

    cap = min(max(limit, 1), 20)
    vis = neo4j_access_params(scope)

    async with driver.session() as session:
        ent_result = await session.run(
            """
            MATCH (e:KnowledgeEntity)
            WHERE any(kw IN $kws WHERE
              toLower(e.name) = toLower(kw)
              OR toLower(replace(replace(e.name, '《', ''), '》', '')) STARTS WITH toLower(kw)
              OR toLower(e.name) ENDS WITH toLower(kw)
              OR any(a IN coalesce(e.aliases, []) WHERE
                toLower(toString(a)) = toLower(kw)
                OR toLower(toString(a)) STARTS WITH toLower(kw)
                OR toLower(toString(a)) ENDS WITH toLower(kw)
              )
            )
            AND (
              $unrestricted OR EXISTS {
                MATCH (d:KnowledgeDocument)-[:HAS_CHUNK]->(:DocumentChunk)-[:MENTIONS]->(e)
                WHERE """
            + neo4j_document_access_where("d")
            + """
              }
            )
            RETURN e.name AS name, e.type AS type, e.description AS description
            ORDER BY
              CASE
                WHEN any(kw IN $kws WHERE toLower(e.name) = toLower(kw)) THEN 0
                WHEN any(kw IN $kws WHERE toLower(e.name) STARTS WITH toLower(kw)
                  OR toLower(e.name) ENDS WITH toLower(kw)) THEN 1
                ELSE 2
              END,
              size(e.name)
            LIMIT $limit
            """,
            {"kws": keywords, "limit": cap, **vis},
        )
        entities = [
            {
                "name": record["name"],
                "type": record["type"],
                "description": record["description"],
            }
            for record in await ent_result.data()
        ]
        names = [entity["name"] for entity in entities]
        if not names:
            logger.info("图谱对话检索无实体：kws=%s", "/".join(keywords))
            return empty

        rel_result = await session.run(
            """
            MATCH (a:KnowledgeEntity)-[r:RELATED_TO]->(b:KnowledgeEntity)
            WHERE a.name IN $names AND b.name IN $names
            RETURN a.name AS source,
                   coalesce(nullif(r.relation, 'RELATED_TO'), '关联') AS relation,
                   b.name AS target
            """,
            {"names": names},
        )
        seen: set[str] = set()
        relations: list[dict[str, str]] = []
        for record in await rel_result.data():
            item = {
                "source": record["source"],
                "relation": record["relation"],
                "target": record["target"],
            }
            key = f"{item['source']}\t{item['relation']}\t{item['target']}"
            if key in seen:
                continue
            seen.add(key)
            relations.append(item)

        doc_result = await session.run(
            """
            MATCH (d:KnowledgeDocument)-[:HAS_CHUNK]->(:DocumentChunk)-[:MENTIONS]->(e:KnowledgeEntity)
            WHERE e.name IN $names
              AND ($unrestricted OR """
            + neo4j_document_access_where("d")
            + """
            )
            RETURN DISTINCT d.id AS documentId, d.title AS title
            LIMIT 8
            """,
            {"names": names, **vis},
        )
        documents = [
            {
                "documentId": record["documentId"],
                "title": record["title"] or "",
            }
            for record in await doc_result.data()
        ]

    logger.info(
        "图谱对话检索：kws=%s entities=%s rels=%s",
        "/".join(keywords),
        len(entities),
        len(relations),
    )
    return {
        "query": " / ".join(keywords),
        "entities": entities,
        "relations": relations,
        "documents": documents,
    }


def format_graph_context(hit: dict[str, Any]) -> str:
    """给模型看的图谱上下文：只写关系与来源，不当制度原文。"""
    if not hit.get("entities") and not hit.get("relations"):
        return ""

    lines: list[str] = []
    relations = hit.get("relations") or []
    if relations:
        lines.append("关系：")
        for rel in relations:
            lines.append(f"- {rel['source']} → {rel['target']}（{rel['relation']}）")
    else:
        names = "、".join(entity["name"] for entity in hit.get("entities") or [])
        lines.append(f"实体：{names}")

    titles = [
        doc["title"]
        for doc in hit.get("documents") or []
        if doc.get("title")
    ]
    if titles:
        lines.append(f"来源文档：{'；'.join(titles)}")
    return "\n".join(lines)


def format_graph_system_text(hit: dict[str, Any]) -> str:
    body = format_graph_context(hit)
    if not body:
        return ""
    return (
        f"【本轮知识图谱】\n{body}\n\n"
        "以上只说明实体之间的关系，不能当制度原文；制度/流程以知识库检索资料为准。"
    )


def merge_graph_hits(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    """合并多轮图谱命中，去重实体 / 关系 / 文档。"""
    names = {entity["name"] for entity in base["entities"]}
    entities = list(base["entities"])
    for entity in extra["entities"]:
        if entity["name"] in names:
            continue
        names.add(entity["name"])
        entities.append(entity)

    rel_keys = {
        f"{rel['source']}\t{rel['relation']}\t{rel['target']}"
        for rel in base["relations"]
    }
    relations = list(base["relations"])
    for rel in extra["relations"]:
        key = f"{rel['source']}\t{rel['relation']}\t{rel['target']}"
        if key in rel_keys:
            continue
        rel_keys.add(key)
        relations.append(rel)

    doc_ids = {doc["documentId"] for doc in base["documents"]}
    documents = list(base["documents"])
    for doc in extra["documents"]:
        if doc["documentId"] in doc_ids:
            continue
        doc_ids.add(doc["documentId"])
        documents.append(doc)

    queries = []
    for raw in f"{base['query']}/{extra['query']}".split("/"):
        word = raw.strip()
        if word and word not in queries:
            queries.append(word)

    return {
        "query": " / ".join(queries),
        "entities": entities,
        "relations": relations,
        "documents": documents,
    }


async def _merge_document_node(
    session: AsyncSession, doc: PipelineDocument, now: str
) -> None:
    await session.run(
        """
        MERGE (d:KnowledgeDocument {id: $id})
        ON CREATE SET d.title = $title, d.summary = $summary,
                     d.categoryId = $categoryId, d.authorId = $authorId,
                     d.teamId = $teamId, d.isPublic = $isPublic,
                     d.status = $status, d.tags = $tags,
                     d.createdAt = $now, d.updatedAt = $now
        ON MATCH SET d.title = $title, d.summary = $summary,
                     d.categoryId = $categoryId, d.authorId = $authorId,
                     d.teamId = $teamId, d.isPublic = $isPublic,
                     d.status = $status, d.tags = $tags, d.updatedAt = $now
        """,
        {
            "id": doc.id,
            "title": doc.title,
            "summary": doc.summary or "",
            "categoryId": doc.category_id,
            "authorId": doc.author_id,
            "teamId": doc.team_id,
            "isPublic": doc.is_public,
            "status": doc.status,
            "tags": doc.tags or "",
            "now": now,
        },
    )


async def _merge_chunk_node(
    session: AsyncSession,
    document_id: str,
    chunk: DocumentChunk,
    now: str,
) -> None:
    await session.run(
        """
        MERGE (c:DocumentChunk {chunkId: $chunkId})
        ON CREATE SET c.documentId = $documentId, c.content = $content,
                     c.heading = $heading, c.chunkIndex = $chunkIndex,
                     c.totalChunks = $totalChunks, c.updatedAt = $now
        ON MATCH SET c.documentId = $documentId, c.content = $content,
                     c.heading = $heading, c.chunkIndex = $chunkIndex,
                     c.totalChunks = $totalChunks, c.updatedAt = $now
        WITH c
        MATCH (d:KnowledgeDocument {id: $documentId})
        MERGE (d)-[r:HAS_CHUNK]->(c)
        SET r.chunkIndex = $chunkIndex
        """,
        {
            "chunkId": chunk.chunk_id,
            "documentId": document_id,
            "content": chunk.content,
            "heading": chunk.heading,
            "chunkIndex": chunk.chunk_index,
            "totalChunks": chunk.total_chunks,
            "now": now,
        },
    )


async def _write_extraction(
    session: AsyncSession,
    result: ExtractionResult,
    now: str,
) -> int:
    count = 0
    for entity in result.entities:
        await session.run(
            """
            MERGE (e:KnowledgeEntity {name: $name})
            ON CREATE SET e.type = $type, e.description = $description,
                          e.aliases = $aliases, e.createdAt = $now, e.updatedAt = $now
            ON MATCH SET e.type = coalesce($type, e.type),
                          e.description = CASE WHEN $description <> ''
                                             THEN $description ELSE e.description END,
                          e.updatedAt = $now
            """,
            {
                "name": entity.name,
                "type": entity.type,
                "description": entity.description or "",
                "aliases": entity.aliases,
                "now": now,
            },
        )
        count += 1

        if result.chunk_id:
            await session.run(
                """
                MATCH (c:DocumentChunk {chunkId: $chunkId})
                MATCH (e:KnowledgeEntity {name: $name})
                MERGE (c)-[r:MENTIONS]->(e)
                """,
                {"chunkId": result.chunk_id, "name": entity.name},
            )

    for rel in result.relations:
        await session.run(
            """
            MATCH (a:KnowledgeEntity {name: $source})
            MATCH (b:KnowledgeEntity {name: $target})
            MERGE (a)-[r:RELATED_TO]->(b)
            ON CREATE SET r.relation = $relation, r.weight = $weight,
                          r.createdAt = $now
            ON MATCH SET r.weight = coalesce($weight, r.weight)
            """,
            {
                "source": rel.source,
                "target": rel.target,
                "relation": rel.relation,
                "weight": rel.weight,
                "now": now,
            },
        )

    return count
