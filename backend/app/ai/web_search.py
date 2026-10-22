"""Bocha 联网搜索。"""

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

BOCHA_ENDPOINT = "https://api.bochaai.com/v1/web-search"


@dataclass
class WebSearchHit:
    title: str
    url: str
    snippet: str
    site_name: str | None = None


@dataclass
class WebSearchResult:
    query: str
    items: list[WebSearchHit] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "query": self.query,
            "items": [
                {
                    "title": item.title,
                    "url": item.url,
                    "snippet": item.snippet,
                    "siteName": item.site_name,
                }
                for item in self.items
            ],
        }
        if self.error:
            payload["error"] = self.error
        return payload


async def search(query: str, count: int = 5) -> WebSearchResult:
    api_key = settings.bocha_api_key
    if not api_key:
        return WebSearchResult(
            query=query, error="未配置 BOCHA_API_KEY，无法联网搜索"
        )

    body = {
        "query": query,
        "freshness": "noLimit",
        "summary": True,
        "count": min(max(count, 1), 10),
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                BOCHA_ENDPOINT,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
        if response.status_code >= 400:
            detail = response.text[:120]
            logger.warning("Bocha 搜索失败：status=%s", response.status_code)
            return WebSearchResult(
                query=query,
                error=f"搜索失败（{response.status_code}）{detail}",
            )
        payload = response.json()
    except Exception as exc:  # pragma: no cover - 外部服务
        logger.warning("Bocha 搜索异常：%s", exc)
        return WebSearchResult(query=query, error=f"搜索失败：{exc}")

    if payload.get("code") != 200 or not payload.get("data"):
        return WebSearchResult(
            query=query, error=payload.get("msg") or "搜索接口返回异常"
        )

    pages = ((payload.get("data") or {}).get("webPages") or {}).get("value") or []
    items = [
        WebSearchHit(
            title=str(page.get("name")),
            url=str(page.get("url")),
            snippet=str(page.get("summary") or page.get("snippet") or "").strip(),
            site_name=page.get("siteName"),
        )
        for page in pages
        if page.get("url") and page.get("name")
    ]
    return WebSearchResult(query=query, items=items)
