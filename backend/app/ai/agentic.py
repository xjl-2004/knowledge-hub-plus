"""检索 + 切题评估的 Agentic 循环。"""

import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from app.ai.query_rewrite import ChatQueryRewrite, HitGrade
from app.core.deps import AuthUser
from app.services.retrieval import retrieve

logger = logging.getLogger(__name__)

EMPTY_GRADE = HitGrade(False, "empty", "未检索到资料")


@dataclass
class RetrieveEval:
    ok: bool
    reason: str
    text: str
    retried: bool
    query: str
    retry_query: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ok": self.ok,
            "reason": self.reason,
            "text": self.text,
            "retried": self.retried,
            "query": self.query,
        }
        if self.retry_query:
            payload["retryQuery"] = self.retry_query
        return payload


@dataclass
class GradedRetrieve:
    raw_hits: list[dict[str, Any]]
    hits: list[dict[str, Any]]
    grade: HitGrade
    eval: RetrieveEval
    used_query: str


@dataclass
class UntilRelevant:
    hits: list[dict[str, Any]]
    eval: RetrieveEval
    used_query: str


async def retrieve_and_grade(
    *,
    question: str,
    query: str,
    top_k: int,
    user: AuthUser | None,
    rewrite: ChatQueryRewrite,
    retried: bool = False,
    previous_query: str | None = None,
) -> GradedRetrieve:
    used_query = query.strip() or question
    display_query = (previous_query or used_query) if retried else used_query
    retry_query = used_query if retried else None

    try:
        raw_hits = await retrieve(used_query, top_k, user)
        grade = await rewrite.grade_hits(question, raw_hits)
        return GradedRetrieve(
            raw_hits=raw_hits,
            hits=raw_hits if grade.ok else [],
            grade=grade,
            eval=_to_eval(grade, display_query, retried, retry_query),
            used_query=used_query,
        )
    except Exception as exc:  # pragma: no cover - 外部检索
        return GradedRetrieve(
            raw_hits=[],
            hits=[],
            grade=HitGrade(False, "empty", f"检索失败：{exc}"),
            eval=RetrieveEval(
                ok=False,
                reason="error",
                text="改写后再次检索失败" if retried else "检索失败",
                retried=retried,
                query=display_query,
                retry_query=retry_query,
            ),
            used_query=used_query,
        )


async def retrieve_until_relevant(
    *,
    question: str,
    query: str,
    top_k: int,
    user: AuthUser | None,
    rewrite: ChatQueryRewrite,
    on_eval: Callable[[RetrieveEval], Awaitable[None]] | None = None,
    on_rewrite: Callable[[str], Awaitable[None]] | None = None,
) -> UntilRelevant:
    """查一次 → 评估 → 不足则改写再查一次（非流式对话用）。"""
    first = await retrieve_and_grade(
        question=question,
        query=query,
        top_k=top_k,
        user=user,
        rewrite=rewrite,
    )
    if on_eval:
        await on_eval(first.eval)
    if first.eval.ok or first.eval.reason == "error":
        return UntilRelevant(first.hits, first.eval, first.used_query)

    retry_query = await rewrite.rewrite_after_retrieve(
        question, first.used_query, first.grade, first.raw_hits
    )
    if not retry_query:
        return UntilRelevant([], first.eval, first.used_query)

    if on_rewrite:
        await on_rewrite(retry_query)
    second = await retrieve_and_grade(
        question=question,
        query=retry_query,
        top_k=top_k,
        user=user,
        rewrite=rewrite,
        retried=True,
        previous_query=first.used_query,
    )
    if on_eval:
        await on_eval(second.eval)
    return UntilRelevant(second.hits, second.eval, second.used_query)


def _to_eval(
    grade: HitGrade,
    query: str,
    retried: bool,
    retry_query: str | None,
) -> RetrieveEval:
    if grade.reason == "relevant":
        return RetrieveEval(
            ok=True,
            reason="retried_ok" if retried else "ok",
            text=f"已改写再查，{grade.text}" if retried else grade.text,
            retried=retried,
            query=query,
            retry_query=retry_query,
        )
    if grade.reason == "empty":
        return RetrieveEval(
            ok=False,
            reason="retried_empty" if retried else "empty",
            text="改写后仍无结果" if retried else grade.text,
            retried=retried,
            query=query,
            retry_query=retry_query,
        )
    return RetrieveEval(
        ok=False,
        reason="retried_irrelevant" if retried else "irrelevant",
        text=f"改写后仍不切题：{grade.text}" if retried else grade.text,
        retried=retried,
        query=query,
        retry_query=retry_query,
    )
