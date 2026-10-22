"""Agentic RAG 流式作答，输出 AI SDK UI Message Stream。"""

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

from openai import AsyncOpenAI

from app.ai import llm, long_memory, sessions, short_memory
from app.ai.agentic import retrieve_and_grade
from app.ai.query_rewrite import ChatRoutePlan, query_rewrite
from app.ai.ui_stream import UIStreamWriter, done_frame, encode
from app.ai.web_search import search as web_search
from app.core.config import settings
from app.core.deps import AuthUser
from app.db.session import SessionLocal
from app.pipeline import graph_build
from app.services.documents import access_from_user

logger = logging.getLogger(__name__)

EXCERPT_LEN = 200
CITATION_RE = re.compile(r"\[(\d+)\]")
MAX_MODEL_CALLS = 8
MAX_RETRIEVE = 2
EMPTY_ANSWER = "未能生成回答。"


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict[str, Any] = field(default_factory=dict)
    arguments: str = ""


async def stream_chat(
    dto: Any, user: AuthUser
) -> AsyncIterator[str]:
    writer = UIStreamWriter()
    question = last_user_text(dto.messages)
    top_k = dto.top_k or 5
    state = _StreamState(question=question)

    yield encode({"type": "start"})

    async with SessionLocal() as db:
        try:
            if not question:
                yield encode({"type": "text-start", "id": "empty"})
                yield encode(
                    {"type": "text-delta", "id": "empty", "delta": "请输入问题。"}
                )
                yield encode({"type": "text-end", "id": "empty"})
                yield encode({"type": "finish"})
                yield done_frame()
                return

            session = await _ensure_session(db, user, dto.session_id, question)
            state.session_id = session["id"]
            yield encode(
                {"type": "data-session", "data": {"sessionId": state.session_id}}
            )

            history = await _load_history(db, user.user_id, state.session_id)
            state.history = history

            writer.write(
                {
                    "type": "data-status",
                    "data": {"stage": "intent", "text": "正在识别意图…"},
                }
            )
            memory_task = asyncio.create_task(
                long_memory.search(user.user_id, state.session_id, question)
            )
            plan = await query_rewrite.classify(question, history)
            writer.write({"type": "data-intent", "data": plan.to_dict()})
            for frame in writer.drain():
                yield frame

            memory_hits = await memory_task

            client = llm.get_client()
            if client is None:
                yield encode(
                    {"type": "error", "errorText": "未配置 LLM Key，无法生成回答"}
                )
                yield encode({"type": "finish"})
                yield done_frame()
                return

            async for frame in _run_agent(
                client,
                dto,
                user,
                plan,
                question,
                top_k,
                history,
                memory_hits,
                writer,
                state,
            ):
                yield frame

            await _persist(user, state, writer)
            for frame in writer.drain():
                yield frame
            yield encode({"type": "finish"})
            yield done_frame()
        except asyncio.CancelledError:
            await _persist(user, state, writer)
            raise
        except GeneratorExit:
            await _persist(user, state, writer)
            raise


@dataclass
class _StreamState:
    question: str
    session_id: str | None = None
    history: list[dict[str, str]] = field(default_factory=list)
    answer: str = ""
    persist_sources: list[dict[str, Any]] = field(default_factory=list)
    persisted: bool = False


async def _ensure_session(
    db, user: AuthUser, session_id: str | None, question: str
) -> dict[str, Any]:
    if session_id:
        return await sessions.touch_title(db, user.user_id, session_id, question)
    return await sessions.create(
        db, user.user_id, sessions.title_from_question(question)
    )


async def _load_history(db, user_id: str, session_id: str) -> list[dict[str, str]]:
    cached = await short_memory.try_load(user_id, session_id)
    if cached is not None:
        return cached
    rows = await sessions.list_recent_messages(
        db, user_id, session_id, short_memory.window_size()
    )
    if rows:
        await short_memory.save(user_id, session_id, rows)
        logger.info("短期记忆从库回填：sessionId=%s, n=%s", session_id, len(rows))
    return rows


async def _persist(user: AuthUser, state: _StreamState, writer: UIStreamWriter) -> None:
    if state.persisted or not state.question or not state.session_id:
        return
    state.persisted = True
    answer = state.answer.strip() or EMPTY_ANSWER
    used = {int(match.group(1)) for match in CITATION_RE.finditer(answer)}
    sources = (
        [src for src in state.persist_sources if src["index"] in used]
        if used
        else []
    )
    try:
        async with SessionLocal() as db:
            await sessions.append_turn(
                db,
                user.user_id,
                state.session_id,
                state.question,
                answer,
                sources,
            )
        await short_memory.append_turn(
            user.user_id,
            state.session_id,
            state.history,
            state.question,
            answer,
        )
        await long_memory.remember_turn(
            user.user_id, state.session_id, state.question, answer
        )
    except Exception as exc:  # pragma: no cover - 落库失败不阻断前端
        logger.warning("流式对话落库失败：%s", exc)


async def _run_agent(
    client: AsyncOpenAI,
    dto: Any,
    user: AuthUser,
    plan: ChatRoutePlan,
    question: str,
    top_k: int,
    history: list[dict[str, str]],
    memory_hits: Any,
    writer: UIStreamWriter,
    state: _StreamState,
) -> AsyncIterator[str]:
    tools = _build_tools(plan, question, top_k, user, writer, state)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _system_for_plan(plan)}
    ]
    memory_text = long_memory.build_system_text(memory_hits)
    if memory_text:
        messages.append({"role": "system", "content": memory_text})
    messages.extend(history)
    messages.append({"role": "user", "content": question})

    specs = [spec for spec, _ in tools]

    for step in range(MAX_MODEL_CALLS):
        writer.write({"type": "start-step"})
        for frame in writer.drain():
            yield frame

        stream = await client.chat.completions.create(
            model=settings.llm_model_name,
            messages=messages,
            temperature=0.2,
            stream=True,
            tools=specs or None,
            timeout=settings.ai_chat_timeout_ms / 1000,
            extra_body={
                **({"enable_thinking": True} if settings.llm_enable_thinking else {}),
                **({"parallel_tool_calls": True} if specs else {}),
            },
        )

        text_id = f"text-{step}"
        reasoning_id = f"reasoning-{step}"
        text_open = False
        reasoning_open = False
        content_parts: list[str] = []
        tool_calls: dict[int, ToolCall] = {}

        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            reasoning = getattr(delta, "reasoning_content", None)
            if not reasoning:
                extra = getattr(delta, "model_extra", None) or {}
                reasoning = extra.get("reasoning_content")
            if reasoning:
                if not reasoning_open:
                    reasoning_open = True
                    yield encode({"type": "reasoning-start", "id": reasoning_id})
                yield encode(
                    {
                        "type": "reasoning-delta",
                        "id": reasoning_id,
                        "delta": reasoning,
                    }
                )
            if delta.content:
                if not text_open:
                    text_open = True
                    yield encode({"type": "text-start", "id": text_id})
                content_parts.append(delta.content)
                yield encode(
                    {"type": "text-delta", "id": text_id, "delta": delta.content}
                )
            for call_delta in delta.tool_calls or []:
                index = call_delta.index or 0
                entry = tool_calls.setdefault(index, ToolCall(id="", name=""))
                if call_delta.id:
                    entry.id = call_delta.id
                function = call_delta.function
                if function:
                    if function.name:
                        entry.name = function.name
                    if function.arguments:
                        entry.arguments += function.arguments
            for frame in writer.drain():
                yield frame

        if reasoning_open:
            yield encode({"type": "reasoning-end", "id": reasoning_id})
        if text_open:
            yield encode({"type": "text-end", "id": text_id})
        writer.write({"type": "finish-step"})
        for frame in writer.drain():
            yield frame

        step_text = "".join(content_parts)
        if step_text.strip():
            state.answer += step_text

        if not tool_calls:
            break

        ordered = [tool_calls[key] for key in sorted(tool_calls)]
        for index, call in enumerate(ordered):
            if not call.id:
                call.id = f"call-{step}-{index}"
            try:
                call.input = json.loads(call.arguments) if call.arguments else {}
            except json.JSONDecodeError:
                call.input = {}
            yield encode(
                {
                    "type": "tool-input-start",
                    "toolCallId": call.id,
                    "toolName": call.name,
                }
            )
            yield encode(
                {
                    "type": "tool-input-available",
                    "toolCallId": call.id,
                    "toolName": call.name,
                    "input": call.input,
                }
            )

        messages.append(
            {
                "role": "assistant",
                "content": step_text or None,
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": call.arguments or "{}",
                        },
                    }
                    for call in ordered
                ],
            }
        )

        executors = dict(tools)
        results = await asyncio.gather(
            *(_execute_tool(executors, call) for call in ordered),
            return_exceptions=True,
        )
        for frame in writer.drain():
            yield frame

        for call, result in zip(ordered, results):
            if isinstance(result, BaseException):
                logger.warning("工具执行失败：%s %s", call.name, result)
                output: dict[str, Any] = {"error": str(result)}
                yield encode(
                    {
                        "type": "tool-output-error",
                        "toolCallId": call.id,
                        "errorText": str(result),
                    }
                )
            else:
                output = result
                yield encode(
                    {
                        "type": "tool-output-available",
                        "toolCallId": call.id,
                        "output": output,
                    }
                )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(output, ensure_ascii=False),
                }
            )


async def _execute_tool(
    tools: dict[str, Any], call: ToolCall
) -> dict[str, Any]:
    runner = tools.get(call.name)
    if runner is None:
        return {"error": f"未知工具：{call.name}"}
    return await runner(call.input)


def _build_tools(
    plan: ChatRoutePlan,
    question: str,
    top_k: int,
    user: AuthUser,
    writer: UIStreamWriter,
    state: _StreamState,
) -> list[tuple[dict[str, Any], Any]]:
    tools: list[tuple[dict[str, Any], Any]] = []
    counter = {"retrieve": 0}
    last: dict[str, Any] = {}

    if plan.allow_retrieve:

        async def retrieve_knowledge(args: dict[str, Any]) -> dict[str, Any]:
            if counter["retrieve"] >= MAX_RETRIEVE:
                return {
                    "query": args.get("query") or "",
                    "items": [],
                    "insufficient": True,
                    "error": "本轮知识库最多检索两次，请根据已有评估作答或联网",
                }
            counter["retrieve"] += 1
            query = str(args.get("query") or "").strip() or question
            requested = args.get("topK") or args.get("top_k") or top_k
            try:
                requested = int(requested)
            except (TypeError, ValueError):
                requested = top_k
            result = await retrieve_and_grade(
                question=question,
                query=query,
                top_k=min(max(requested, 1), 10),
                user=user,
                rewrite=query_rewrite,
                retried=counter["retrieve"] > 1,
                previous_query=last.get("used_query"),
            )
            last["result"] = result
            writer.write({"type": "data-eval", "data": result.eval.to_dict()})
            if result.eval.reason == "error":
                logger.warning("RAG 检索失败：%s", result.eval.text)
                return {
                    "query": result.used_query,
                    "items": [],
                    "error": result.eval.text,
                    "insufficient": True,
                    "eval": result.eval.to_dict(),
                }
            if not result.eval.ok:
                return _pack_retrieve_result(
                    [],
                    result.used_query,
                    state.persist_sources,
                    writer,
                    {"insufficient": True, "eval": result.eval.to_dict()},
                )
            return _pack_retrieve_result(
                result.hits,
                result.used_query,
                state.persist_sources,
                writer,
                {"eval": result.eval.to_dict()},
            )

        tools.append(
            (
                _spec(
                    "retrieve_knowledge",
                    "检索企业知识库一次（仅当前用户可见文档）并评估是否切题。不会自动再查。"
                    "首次必须与 retrieve_graph 在同一次并行调用。eval.ok 为 false 时先 "
                    "rewrite_query，再用新词再调本工具。本轮最多两次。",
                    {
                        "query": {
                            "type": "string",
                            "description": "适合检索的关键词或短句",
                        },
                        "topK": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 10,
                            "description": "条数，默认与请求一致",
                        },
                    },
                    ["query"],
                ),
                retrieve_knowledge,
            )
        )

        async def rewrite_query(args: dict[str, Any]) -> dict[str, Any]:
            result = last.get("result")
            if result is None:
                return {"error": "请先调用 retrieve_knowledge"}
            if result.eval.ok:
                return {"error": "当前资料已切题，无需改写", "query": result.used_query}
            writer.write(
                {
                    "type": "data-status",
                    "data": {"stage": "rewrite", "text": "正在改写检索词…"},
                }
            )
            retry_query = await query_rewrite.rewrite_after_retrieve(
                question, result.used_query, result.grade, result.raw_hits
            )
            if not retry_query:
                return {
                    "error": "无法改写出与上次不同的检索词",
                    "previousQuery": result.used_query,
                    "reason": result.eval.text,
                }
            return {
                "query": retry_query,
                "previousQuery": result.used_query,
                "reason": result.eval.text,
                "focus": args.get("focus"),
            }

        tools.append(
            (
                _spec(
                    "rewrite_query",
                    "根据上次检索评估改写检索词。仅在 retrieve_knowledge 返回 "
                    "insufficient 后调用，再把返回的 query 交给 retrieve_knowledge。",
                    {
                        "focus": {
                            "type": "string",
                            "description": "希望改写时强调的缺口，可空",
                        }
                    },
                    [],
                ),
                rewrite_query,
            )
        )

    if plan.allow_graph:

        async def retrieve_graph(args: dict[str, Any]) -> dict[str, Any]:
            query = str(args.get("query") or "").strip()
            keywords = list(plan.graph_queries)
            if query:
                keywords.append(query)
            hit = await graph_build.retrieve_for_chat(
                keywords, 8, access_from_user(user)
            )
            writer.write({"type": "data-graph", "data": hit})
            return {
                "query": hit.get("query") or "",
                "entities": hit.get("entities") or [],
                "relations": hit.get("relations") or [],
                "documents": hit.get("documents") or [],
                "context": graph_build.format_graph_context(hit),
                "insufficient": not hit.get("entities") and not hit.get("relations"),
            }

        tools.append(
            (
                _spec(
                    "retrieve_graph",
                    "检索知识图谱实体与关系（仅当前用户可见文档抽取出的图）。入参必须是短实体名，"
                    "多个用空格或 / 分隔，例如「发票 / 报销」，不要整句。首次检索知识库时必须与 "
                    "retrieve_knowledge 在同一次并行调用。图谱只说明实体关系，不能当制度原文。"
                    "仅当还要查其他实体名时再单独再调。",
                    {
                        "query": {
                            "type": "string",
                            "description": "短实体名，多个用空格或 / 分隔，不要整句",
                        }
                    },
                    ["query"],
                ),
                retrieve_graph,
            )
        )

    if plan.allow_web:

        async def web_search_tool(args: dict[str, Any]) -> dict[str, Any]:
            query = str(args.get("query") or "").strip()
            count = args.get("count") or 5
            try:
                count = int(count)
            except (TypeError, ValueError):
                count = 5
            result = await web_search(query, count)
            return result.to_dict()

        tools.append(
            (
                _spec(
                    "web_search",
                    "联网搜索公开信息（Bocha）。仅在知识库循环结束后仍 insufficient，"
                    "或本轮只需公开时效信息时调用。不要用网页替代已切题的知识库资料。",
                    {
                        "query": {"type": "string", "description": "搜索关键词"},
                        "count": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 10,
                            "description": "条数，默认 5",
                        },
                    },
                    ["query"],
                ),
                web_search_tool,
            )
        )

    return tools


def _spec(
    name: str,
    description: str,
    properties: dict[str, Any],
    required: list[str],
) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }


def _pack_retrieve_result(
    hits: list[dict[str, Any]],
    query: str,
    persist_sources: list[dict[str, Any]],
    writer: UIStreamWriter,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    offset = len(persist_sources)
    sources = [
        {
            "index": offset + index + 1,
            "documentId": hit.get("documentId") or "",
            "documentTitle": hit.get("documentTitle") or "",
            "heading": hit.get("heading"),
            "excerpt": _excerpt(hit.get("content") or ""),
            "score": hit.get("score") or 0.0,
        }
        for index, hit in enumerate(hits)
    ]
    persist_sources.extend(sources)
    writer.write({"type": "data-sources", "data": persist_sources})
    for src in sources:
        writer.write(
            {
                "type": "source-document",
                "sourceId": src["documentId"],
                "mediaType": "text/markdown",
                "title": f"[{src['index']}] {src['documentTitle']}",
            }
        )
    context_blocks: list[str] = []
    for index, hit in enumerate(hits):
        src = sources[index]
        heading = f" / {hit['heading']}" if hit.get("heading") else ""
        content = hit.get("content") or ""
        snippet = f"{content[:800]}..." if len(content) > 800 else content
        context_blocks.append(
            f"[{src['index']}] {hit.get('documentTitle') or ''}{heading}\n{snippet}"
        )
    return {
        "query": query,
        "items": [
            {
                "index": src["index"],
                "documentId": src["documentId"],
                "documentTitle": src["documentTitle"],
                "heading": src["heading"],
                "excerpt": src["excerpt"],
            }
            for src in sources
        ],
        "context": "\n\n".join(context_blocks),
        **(extra or {}),
    }


def _excerpt(content: str) -> str:
    text = re.sub(r"\s+", " ", content or "").strip()
    if len(text) <= EXCERPT_LEN:
        return text
    return f"{text[:EXCERPT_LEN]}..."


def _system_for_plan(plan: ChatRoutePlan) -> str:
    prompt = (
        "你是企业知识库助手，必须按 Agentic RAG 循环作答，不要跳步。"
        "结合对话历史和记忆里的用户背景，但制度/流程以本轮检索资料为准。"
        f"本轮意图：{plan.label}。"
    )
    if plan.allow_retrieve and plan.allow_graph:
        graph_hint = (
            " / ".join(plan.graph_queries)
            if plan.graph_queries
            else "从问题抽出的短实体名"
        )
        prompt += (
            f"知识库建议检索词「{plan.query}」，图谱建议检索词「{graph_hint}」。"
            "第一步必须在同一次回复里并行调用 retrieve_knowledge 和 retrieve_graph，两个都要调："
            "不要先查库再决定是否查图，不要只调其中一个，也不要等一个返回再调另一个。"
            "retrieve_graph 的 query 必须是短实体名（空格或 / 分隔），不要整句。"
            "循环：① 并行检索；② 若知识库 eval.ok 则用文档 context 作答并标 [n]，"
            "图谱只看实体关系、不能当制度原文；"
            "③ 若 insufficient，先 rewrite_query，再用新词再次 retrieve_knowledge（知识库最多两次）；"
            "图谱词变了才再调 retrieve_graph；④ 两次后仍不足再考虑联网。"
            "eval.ok 后不要再检索、不要改写。不要第三次 retrieve_knowledge。"
            "图谱为空不要编造关系。不要用记忆替代文档。"
        )
    elif plan.allow_retrieve:
        prompt += (
            f"建议检索词「{plan.query}」，可改写成更准的 query。"
            "循环：① retrieve_knowledge；② 若 eval.ok 则用 context 作答并标 [n]；"
            "③ 若 insufficient，先 rewrite_query，再用返回的新词再次 retrieve_knowledge"
            "（知识库最多两次）；④ 两次后仍不足再考虑联网。"
            "eval.ok 后不要再检索、不要改写。不要第三次 retrieve_knowledge。"
            "不要用记忆替代文档。"
        )
    else:
        prompt += "不要调用 retrieve_knowledge 或 rewrite_query。"
    if not plan.allow_graph:
        prompt += "不要调用 retrieve_graph。"
    if plan.intent == "chitchat":
        prompt += "这是闲聊，直接回应，不要调用任何工具。"
    if plan.intent == "profile":
        prompt += "这是个人偏好或身份问题，根据记忆回答，不要检索知识库。"
    if plan.intent == "kb":
        prompt += "两次检索后仍 insufficient：明确说知识库没有相关内容，禁止编造制度，不要联网。"
    if plan.intent == "web":
        prompt += "用 web_search 查公开信息，用标题+链接说明，不要编造。"
    if plan.intent == "kb_then_web":
        prompt += (
            "先走完知识库循环；两次后仍 insufficient 再 web_search。"
            "联网结果用标题+链接说明，不要把网页写成内部制度。"
        )
    if not plan.allow_web:
        prompt += "不要调用 web_search。"
    prompt += "资料不够就明确说不知道。"
    return prompt


def last_user_text(messages: list[dict[str, Any]] | None) -> str:
    if not messages:
        return ""
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        parts = message.get("parts") or []
        text = "".join(
            str(part.get("text") or "")
            for part in parts
            if isinstance(part, dict) and part.get("type") == "text"
        )
        return text.strip()
    return ""
