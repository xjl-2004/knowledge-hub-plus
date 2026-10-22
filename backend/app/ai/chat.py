"""非流式 Agentic RAG 对话。"""

import logging
import re
from typing import Any

from app.ai import llm, long_memory, short_memory
from app.ai.agentic import retrieve_until_relevant
from app.ai.query_rewrite import ChatRoutePlan, query_rewrite
from app.ai.web_search import WebSearchResult, search as web_search
from app.core import errors
from app.core.config import settings
from app.core.deps import AuthUser
from app.pipeline import graph_build
from app.services.documents import access_from_user

logger = logging.getLogger(__name__)

EXCERPT_LEN = 200
CITATION_RE = re.compile(r"\[(\d+)\]")


def excerpt(content: str) -> str:
    text = re.sub(r"\s+", " ", content or "").strip()
    if len(text) <= EXCERPT_LEN:
        return text
    return f"{text[:EXCERPT_LEN]}..."


def to_cited_sources(
    answer: str, hits: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """从回答中抽出 [n]，只返回实际引用的资料；未标注时回退为全部召回。"""
    cited = {
        int(match.group(1))
        for match in CITATION_RE.finditer(answer)
        if 1 <= int(match.group(1)) <= len(hits)
    }
    indexes = sorted(cited) if cited else list(range(1, len(hits) + 1))
    return [_to_source(index, hits[index - 1]) for index in indexes]


def _to_source(index: int, hit: dict[str, Any]) -> dict[str, Any]:
    return {
        "index": index,
        "documentId": hit.get("documentId") or "",
        "documentTitle": hit.get("documentTitle") or "",
        "heading": hit.get("heading"),
        "excerpt": excerpt(hit.get("content") or ""),
        "score": hit.get("score") or 0.0,
    }


def build_context(hits: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for index, hit in enumerate(hits):
        heading = f" / {hit['heading']}" if hit.get("heading") else ""
        content = hit.get("content") or ""
        snippet = f"{content[:800]}..." if len(content) > 800 else content
        blocks.append(
            f"[{index + 1}] {hit.get('documentTitle') or ''}{heading}\n{snippet}"
        )
    return "\n\n".join(blocks)


def build_web_context(web: WebSearchResult) -> str:
    if web.error:
        return web.error
    if not web.items:
        return "无结果。"
    return "\n\n".join(
        f"{index + 1}. {hit.title}\n{hit.url}\n{hit.snippet}"
        for index, hit in enumerate(web.items)
    )


def build_system_prompt(
    intent: str, has_kb: bool, web: WebSearchResult | None = None
) -> str:
    prompt = (
        "你是企业知识库助手。结合对话历史和记忆里的用户背景回答。"
        "制度/流程以本轮知识库资料为准，不要用记忆替代文档。"
    )
    if has_kb:
        prompt += (
            "凡是依据某条资料作出的陈述，必须在句末标注对应编号，如 [1]、[2]。"
            "编号必须与资料列表一致，不要标注未使用的编号，不要编造文档标题或链接。"
        )
    elif intent in ("kb", "kb_then_web"):
        prompt += "知识库没有切题资料，不要编造内部制度。"
    if web and web.items:
        prompt += "联网结果只作公开信息补充，用标题+链接说明，不要写成公司内部规定。"
    if intent in ("chitchat", "profile"):
        prompt += "可回应寒暄或个人偏好，不要编造制度。"
    prompt += "若资料不足以回答，明确说不知道。回答简洁，必要时列出条目。"
    return prompt


async def load_working_history(
    db, user_id: str, session_id: str | None
) -> list[dict[str, str]]:
    if not session_id:
        return []
    cached = await short_memory.try_load(user_id, session_id)
    if cached is not None:
        return cached
    rows = await _recent_messages(db, user_id, session_id)
    if rows:
        await short_memory.save(user_id, session_id, rows)
    return rows


async def _recent_messages(
    db, user_id: str, session_id: str
) -> list[dict[str, str]]:
    from app.ai import sessions

    return await sessions.list_recent_messages(
        db, user_id, session_id, short_memory.window_size()
    )


async def chat(
    db,
    question: str,
    top_k: int,
    user: AuthUser,
    session_id: str | None = None,
) -> dict[str, Any]:
    trimmed = (question or "").strip()
    if not trimmed:
        return {
            "sessionId": session_id,
            "answer": "请输入问题。",
            "sources": [],
        }

    history = await load_working_history(db, user.user_id, session_id)
    plan = await query_rewrite.classify(trimmed, history)
    memory_hits = await long_memory.search(user.user_id, session_id, plan.query)
    access = access_from_user(user)

    graph_hit: dict[str, Any] | None = None
    if plan.allow_graph and plan.graph_queries:
        graph_hit = await graph_build.retrieve_for_chat(
            plan.graph_queries, 8, access
        )

    retrieved = None
    if plan.allow_retrieve:
        retrieved = await retrieve_until_relevant(
            question=trimmed,
            query=plan.query or trimmed,
            top_k=top_k,
            user=user,
            rewrite=query_rewrite,
        )
        hits = retrieved.hits
        kb_insufficient = not retrieved.eval.ok
        search_query = retrieved.used_query or plan.query or trimmed
    else:
        hits = []
        kb_insufficient = False
        search_query = plan.query or trimmed

    has_graph = bool(
        graph_hit
        and (graph_hit.get("entities") or graph_hit.get("relations"))
    )

    web: WebSearchResult | None = None
    if plan.allow_web and (not plan.allow_retrieve or kb_insufficient):
        web = await web_search(search_query)

    if plan.intent == "kb" and kb_insufficient and not has_graph:
        empty_answer = "知识库里没有相关内容。"
        session = await _persist(db, user.user_id, session_id, trimmed, empty_answer, [])
        await _remember(
            user.user_id,
            session["id"],
            history,
            trimmed,
            empty_answer,
        )
        return {
            "sessionId": session["id"] if session else session_id,
            "answer": empty_answer,
            "sources": [],
        }

    client = llm.get_client()
    if client is None:
        raise errors.unavailable(
            "未配置 OPENAI_API_KEY / LLM_API_KEY / DASHSCOPE_API_KEY，无法生成回答"
        )

    messages = _build_messages(
        plan, hits, web, memory_hits, graph_hit, history, trimmed
    )
    response = await client.chat.completions.create(
        model=settings.llm_model_name,
        messages=messages,
        temperature=0.2,
        timeout=settings.ai_chat_timeout_ms / 1000,
    )
    answer = response.choices[0].message.content or ""
    sources = to_cited_sources(answer, hits)
    logger.info(
        "RAG 对话完成：hits=%s, cited=%s, answerLength=%s",
        len(hits),
        len(sources),
        len(answer),
    )

    session = await _persist(db, user.user_id, session_id, trimmed, answer, sources)
    await _remember(user.user_id, session["id"], history, trimmed, answer)
    return {
        "sessionId": session["id"] if session else session_id,
        "answer": answer,
        "sources": sources,
    }


def _build_messages(
    plan: ChatRoutePlan,
    hits: list[dict[str, Any]],
    web: WebSearchResult | None,
    memory_hits,
    graph_hit: dict[str, Any] | None,
    history: list[dict[str, str]],
    question: str,
) -> list[dict[str, str]]:
    messages = [
        {
            "role": "system",
            "content": build_system_prompt(plan.intent, bool(hits), web),
        }
    ]
    memory_text = long_memory.build_system_text(memory_hits)
    if memory_text:
        messages.append({"role": "system", "content": memory_text})
    graph_text = graph_build.format_graph_system_text(graph_hit) if graph_hit else ""
    if graph_text:
        messages.append({"role": "system", "content": graph_text})

    messages.extend(history)

    parts: list[str] = []
    if hits:
        parts.append(f"知识库资料：\n{build_context(hits)}")
    if web:
        parts.append(f"联网结果：\n{build_web_context(web)}")
    parts.append(f"用户问题：{question}")
    messages.append({"role": "user", "content": "\n\n".join(parts)})
    return messages


async def _persist(
    db,
    user_id: str,
    session_id: str | None,
    question: str,
    answer: str,
    sources: list[dict[str, Any]],
) -> dict[str, Any]:
    from app.ai import sessions

    return await sessions.append_turn(
        db, user_id, session_id, question, answer, sources
    )


async def _remember(
    user_id: str,
    session_id: str,
    history: list[dict[str, str]],
    question: str,
    answer: str,
) -> None:
    await short_memory.append_turn(user_id, session_id, history, question, answer)
    await long_memory.remember_turn(user_id, session_id, question, answer)
