"""大模型调用封装：DashScope OpenAI 兼容接口。"""

import json
import logging
from typing import Any

from openai import AsyncOpenAI

from app.core.config import settings

logger = logging.getLogger(__name__)

_client: AsyncOpenAI | None = None


def is_configured() -> bool:
    return bool(settings.llm_key)


def get_client(timeout_seconds: float | None = None) -> AsyncOpenAI | None:
    if not settings.llm_key:
        return None
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=settings.llm_key,
            base_url=settings.llm_base,
            timeout=(timeout_seconds or settings.ai_chat_timeout_ms / 1000),
            max_retries=0,
        )
    return _client


async def chat_json(
    system_prompt: str,
    user_prompt: str,
    *,
    timeout_ms: int | None = None,
) -> dict[str, Any] | None:
    """结构化 JSON 输出；未配置 Key 时返回 None，解析失败抛异常由调用方兜底。"""
    client = get_client()
    if client is None:
        return None
    response = await client.chat.completions.create(
        model=settings.llm_model_name,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0,
        response_format={"type": "json_object"},
        timeout=(timeout_ms or settings.ai_query_rewrite_timeout_ms) / 1000,
    )
    text = response.choices[0].message.content or ""
    return json.loads(text)
