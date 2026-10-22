"""实体 / 关系抽取（LLM 结构化输出）。"""

import json
import logging
from typing import Any

from openai import AsyncOpenAI

from app.core.config import settings
from app.pipeline.kg_schema import (
    build_extraction_system_prompt,
    normalize_entity_type,
    normalize_relation_type,
)
from app.pipeline.types import (
    ExtractedEntity,
    ExtractedRelation,
    ExtractionResult,
)

logger = logging.getLogger(__name__)

MAX_CONTENT_LENGTH = 4000


def _client() -> AsyncOpenAI | None:
    if not settings.llm_key:
        return None
    return AsyncOpenAI(
        api_key=settings.llm_key,
        base_url=settings.llm_base,
        timeout=max(settings.kg_llm_timeout_ms, 1000) / 1000,
    )


async def extract(
    content: str,
    heading: str | None,
    document_title: str,
) -> ExtractionResult:
    """对单个 chunk 抽取实体与关系。"""
    if not content.strip():
        return ExtractionResult()

    client = _client()
    if client is None:
        raise RuntimeError(
            "KG 抽取未配置 API Key（OPENAI_API_KEY / LLM_API_KEY / DASHSCOPE_API_KEY）"
        )

    system = build_extraction_system_prompt(
        settings.kg_max_entities, settings.kg_max_relations
    )
    user = (
        f"文档标题: {document_title}\n"
        f"章节: {heading or '无'}\n\n"
        f"内容:\n{content[:MAX_CONTENT_LENGTH]}"
    )

    response = await client.chat.completions.create(
        model=settings.llm_model_name,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.1,
        response_format={"type": "json_object"},
    )
    raw = response.choices[0].message.content or "{}"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"KG 抽取返回非法 JSON：{exc}") from exc

    result = _normalize(parsed)
    logger.info(
        "KG 抽取完成：title=%s, chars=%s, entities=%s",
        document_title,
        len(content),
        len(result.entities),
    )
    return result


def _normalize(parsed: dict[str, Any]) -> ExtractionResult:
    """截断数量、规范化类型、丢掉挂空实体的关系。"""
    max_entities = settings.kg_max_entities
    max_relations = settings.kg_max_relations

    entities: list[ExtractedEntity] = []
    names: set[str] = set()
    for item in (parsed.get("entities") or [])[:max_entities]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        names.add(name)
        aliases = [
            str(alias).strip()
            for alias in (item.get("aliases") or [])
            if str(alias).strip()
        ]
        entities.append(
            ExtractedEntity(
                name=name,
                type=normalize_entity_type(item.get("type")),
                description=str(item.get("description") or "").strip(),
                aliases=aliases,
            )
        )

    relations: list[ExtractedRelation] = []
    for item in (parsed.get("relations") or [])[:max_relations]:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source") or "").strip()
        target = str(item.get("target") or "").strip()
        if not source or not target or source not in names or target not in names:
            continue
        weight = item.get("weight")
        relations.append(
            ExtractedRelation(
                source=source,
                target=target,
                relation=normalize_relation_type(
                    item.get("relation") or item.get("type")
                ),
                weight=float(weight) if isinstance(weight, (int, float)) else 0.5,
            )
        )

    return ExtractionResult(entities=entities, relations=relations)
