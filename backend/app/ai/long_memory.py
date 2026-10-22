"""对话长期记忆（Mem0）：未配置 Key 时全部跳过。"""

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.ai import llm
from app.core.config import settings

logger = logging.getLogger(__name__)

CLASSIFIER_PROMPT = (
    "你是企业知识库助手的记忆分类器。判断本轮是否有「新事实」要写入 Mem0。\n\n"
    "## user 层（跨会话）\n"
    "- 用户身份、岗位、所在团队自称\n"
    "- 长期偏好：答短一点、只要本团队制度、技术回答带示例\n"
    "- 持久约束：过敏、语言、称呼\n\n"
    "## session 层（仅当前会话）\n"
    "- 正在排查的问题、本次要写的文档、已确认的下一步\n"
    "- 用户说「这次」「本轮」的工作上下文\n\n"
    "## 均不写入\n"
    "- 寒暄、致谢、纯确认\n"
    "- 助手根据知识库/检索资料说出的制度、流程、负责人、系统名（那是文档事实，不是用户记忆）\n"
    "- 联网搜索结果、引用编号 [n]\n"
    "- 无信息增量的复述\n\n"
    "## 原则\n"
    "1. 知识库内容永远不要写成 user 记忆\n"
    "2. 「这次先看差旅制度第三节」→ session，不要标成 user\n"
    "3. user 与 session 可同时为 true\n"
    "4. 一次性提问且未产生需跨轮记住的约定 → 均为 false\n\n"
    '只返回 JSON：{"write_user":true,"write_session":false,"reason":"一句中文"}'
)

ADD_INSTRUCTIONS = (
    "只用用户说的话抽取记忆，一句完整中文。"
    "只保存身份、岗位、偏好、约束，或用户声明的本轮任务。"
    "不要保存制度条文、流程、时限、负责人、系统名、引用编号。"
    "不要译成英文。"
)


@dataclass
class LongMemoryHits:
    user: list[str] = field(default_factory=list)
    session: list[str] = field(default_factory=list)


def is_enabled() -> bool:
    return bool(settings.mem0_api_key)


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Token {settings.mem0_api_key}",
        "Content-Type": "application/json",
    }


def _base() -> str:
    return settings.mem0_host.rstrip("/")


async def search(
    user_id: str, session_id: str | None, query: str
) -> LongMemoryHits:
    if not is_enabled():
        return LongMemoryHits()
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            user_items = await _search(client, query, {"user_id": user_id})
            session_items: list[str] = []
            if session_id:
                session_items = await _search(
                    client,
                    query,
                    {"AND": [{"user_id": user_id}, {"run_id": session_id}]},
                )
        return LongMemoryHits(user_items, session_items)
    except Exception as exc:  # pragma: no cover - 外部服务
        logger.warning("Mem0 检索失败：%s", exc)
        return LongMemoryHits()


async def _search(
    client: httpx.AsyncClient, query: str, filters: dict[str, Any]
) -> list[str]:
    response = await client.post(
        f"{_base()}/v1/memories/search/",
        headers=_headers(),
        json={"query": query, "filters": filters, "top_k": settings.mem0_top_k},
    )
    response.raise_for_status()
    payload: Any = response.json()
    rows = payload if isinstance(payload, list) else (payload.get("results") or [])
    return [
        str(row.get("memory") or row.get("text")).strip()
        for row in rows
        if isinstance(row, dict) and (row.get("memory") or row.get("text"))
    ]


def build_system_text(hits: LongMemoryHits) -> str:
    blocks: list[str] = []
    if hits.user:
        blocks.append(
            "【用户长期记忆】\n" + "\n".join(f"- {line}" for line in hits.user)
        )
    if hits.session:
        blocks.append(
            "【当前会话记忆】\n"
            + "\n".join(f"- {line}" for line in hits.session)
        )
    if not blocks:
        return ""
    return (
        "\n\n".join(blocks)
        + "\n\n以上仅作背景，制度/流程以本轮检索资料为准，不要用记忆替代文档。"
    )


async def remember_turn(
    user_id: str, session_id: str, question: str, answer: str
) -> None:
    if not is_enabled() or not llm.is_configured():
        return
    try:
        parsed = await llm.chat_json(
            CLASSIFIER_PROMPT,
            (
                f"用户：{question}\n"
                f"助手（仅供判断，不要当作用户事实）：{answer[:300]}"
            ),
            timeout_ms=settings.ai_chat_timeout_ms,
        )
        if not parsed:
            return
        write_user = bool(parsed.get("write_user"))
        write_session = bool(parsed.get("write_session"))
        reason = str(parsed.get("reason") or "")
        written: list[str] = []
        async with httpx.AsyncClient(timeout=20) as client:
            if write_user:
                await _add(client, question, user_id, None)
                written.append("user")
            if write_session:
                await _add(client, question, user_id, session_id)
                written.append("session")
        logger.info("Mem0 分类：%s；写入=%s", reason, ",".join(written) or "无")
    except Exception as exc:  # pragma: no cover - 外部服务
        logger.warning("Mem0 写入失败：%s", exc)


async def _add(
    client: httpx.AsyncClient,
    question: str,
    user_id: str,
    session_id: str | None,
) -> None:
    body: dict[str, Any] = {
        "messages": [{"role": "user", "content": question}],
        "user_id": user_id,
        "custom_instructions": ADD_INSTRUCTIONS,
    }
    if session_id:
        body["run_id"] = session_id
    response = await client.post(
        f"{_base()}/v1/memories/", headers=_headers(), json=body
    )
    response.raise_for_status()


async def clear_session(user_id: str, session_id: str) -> None:
    if not is_enabled():
        return
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            await client.delete(
                f"{_base()}/v1/memories/",
                headers=_headers(),
                params={"user_id": user_id, "run_id": session_id},
            )
    except Exception as exc:  # pragma: no cover - 外部服务
        logger.warning("Mem0 会话层清理失败：%s", exc)
