"""对话意图路由、检索切题评估与检索词改写。"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from app.ai import llm

logger = logging.getLogger(__name__)

ChatIntent = Literal["chitchat", "profile", "kb", "web", "kb_then_web"]

CHAT_INTENTS: tuple[ChatIntent, ...] = (
    "chitchat",
    "profile",
    "kb",
    "web",
    "kb_then_web",
)

INTENT_LABEL: dict[str, str] = {
    "chitchat": "闲聊",
    "profile": "个人偏好",
    "kb": "知识库",
    "web": "联网搜索",
    "kb_then_web": "知识库，不足则联网",
}

ROUTE_PROMPT = (
    "你是企业知识库的意图与检索改写器。根据对话判断本轮意图，给出文档检索句，"
    "以及图谱要用的短实体名。\n\n"
    "## intent\n"
    "- chitchat：问好、致谢、与库无关的闲聊\n"
    "- profile：只问/改「我自己」的名字、我所在部门、回答长短偏好。主语必须是用户本人\n"
    "- kb：公司制度、流程、岗位、内部系统、文档\n"
    "- web：只要最新公开信息，明显不是内部制度\n"
    "- kb_then_web：像内部问题但也可能要外部时效（政策新闻+内部流程）\n\n"
    "## 易混\n"
    "- 「我是哪个部门 / 以后回答短一点」→ profile\n"
    "- 「预算审核员属于哪个部门」→ kb，不要因为出现「部门」就判 profile\n"
    "- 记忆里的用户部门不能改变本题意图\n\n"
    "## standalone_query\n"
    "- 给知识库全文检索用，可以是一句；消解「这个 / 谁负责 / 怎么办」，尽量不超过 40 字\n"
    "- 不要编造上文没有的专有名词、条款号\n"
    "- 不要复述助手已给出的制度条文\n"
    "- 闲聊/偏好：用原问题即可\n\n"
    "## graph_queries\n"
    "- 只在 kb / kb_then_web 填写，其他意图必须空数组\n"
    "- 每个词 2～4 个字的实体短名（人/岗/制度对象），不要整句、不要问号\n"
    "- 必须拆开：发票如何报销 → 发票、报销；发票报销流程和要求 → 发票、报销\n"
    "- 可补 1 个同域短名（报销可带差旅）\n"
    "- 禁止：流程、要求、办法、如何、怎么、什么、是什么\n"
    "- 输出不要解释"
)

ROUTE_OUTPUT_HINT = (
    '\n\n只返回 JSON：{"intent":"chitchat|profile|kb|web|kb_then_web",'
    '"standalone_query":"...","graph_queries":["..."]}'
)

GRADE_PROMPT = (
    "你是企业知识库的检索评估器。判断命中资料能否回答用户问题。\n\n"
    "- 切题：同一主题、同一制度/岗位/流程，能支撑作答（不必覆盖每个细节）\n"
    "- 不切题：只是词沾边（如问加班餐补却命中差旅报销）、或完全另一件事\n"
    "- 只根据给定标题和摘录判断，不要假设库里还有别的文档\n"
    "- 输出不要解释字段以外的内容"
)

GRADE_OUTPUT_HINT = '\n\n只返回 JSON：{"relevant":true,"reason":"一句中文"}'

RETRY_REWRITE_PROMPT = (
    "你是企业知识库的检索改写器。上次检索不足，请换一种问法再查。\n\n"
    "- 紧扣用户原问题，不要跑题\n"
    "- 不要重复上次检索词\n"
    "- 可换同义、补全制度/岗位/补贴类型等核心实体\n"
    "- 不要编造条款号、专有名词\n"
    "- 一句中文，尽量不超过 40 字"
)

RETRY_OUTPUT_HINT = '\n\n只返回 JSON：{"query":"新的检索词"}'


@dataclass
class ChatRoutePlan:
    intent: str
    label: str
    query: str
    graph_queries: list[str] = field(default_factory=list)
    allow_retrieve: bool = False
    allow_graph: bool = False
    allow_web: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "intent": self.intent,
            "label": self.label,
            "query": self.query,
            "graphQueries": self.graph_queries,
            "allowRetrieve": self.allow_retrieve,
            "allowGraph": self.allow_graph,
            "allowWeb": self.allow_web,
        }


@dataclass
class HitGrade:
    ok: bool
    reason: str
    text: str


class ChatQueryRewrite:
    """意图识别、切题评估、检索词改写；无 Key 时按可用性降级。"""

    async def classify(
        self, question: str, history: list[dict[str, str]]
    ) -> ChatRoutePlan:
        fallback = self._to_plan("kb", question)
        context = compact_rewrite_context(history)
        user_prompt = (
            f"对话：\n{context}\n\n当前问题：{question}"
            if context
            else f"当前问题：{question}"
        )
        if not llm.is_configured():
            return fallback
        try:
            parsed = await llm.chat_json(ROUTE_PROMPT + ROUTE_OUTPUT_HINT, user_prompt)
            if not parsed:
                return fallback
            intent = str(parsed.get("intent") or "").strip()
            if intent not in CHAT_INTENTS:
                return fallback
            query = str(parsed.get("standalone_query") or "").strip() or question
            raw_graph = parsed.get("graph_queries") or []
            graph_queries = (
                [str(item).strip() for item in raw_graph if str(item).strip()]
                if isinstance(raw_graph, list)
                else []
            )
            plan = self._to_plan(intent, query, graph_queries)
            logger.info(
                "意图：%s query=%s graph=%s",
                plan.intent,
                plan.query[:80],
                "/".join(plan.graph_queries) or "-",
            )
            return plan
        except Exception as exc:  # pragma: no cover - 外部模型
            logger.warning("意图识别失败，按知识库处理：%s", exc)
            return fallback

    async def grade_hits(self, question: str, hits: list[dict[str, Any]]) -> HitGrade:
        if not hits:
            return HitGrade(False, "empty", "未检索到资料")
        if not llm.is_configured():
            return HitGrade(True, "relevant", "有召回（未配置评估模型）")
        try:
            parsed = await llm.chat_json(
                GRADE_PROMPT + GRADE_OUTPUT_HINT,
                f"用户问题：{question}\n\n命中资料：\n{summarize_hits(hits)}",
            )
            ok = bool(parsed.get("relevant")) if parsed else True
            text = (
                str(parsed.get("reason") or "").strip()
                if parsed
                else ""
            ) or ("资料切题" if ok else "资料不切题")
            logger.info("检索评估：%s %s", "切题" if ok else "不切题", text[:80])
            return HitGrade(ok, "relevant" if ok else "irrelevant", text)
        except Exception as exc:  # pragma: no cover - 外部模型
            logger.warning("检索评估失败，按有召回放行：%s", exc)
            return HitGrade(True, "relevant", "评估失败，按有召回处理")

    async def rewrite_after_retrieve(
        self,
        question: str,
        previous_query: str,
        grade: HitGrade,
        hits: list[dict[str, Any]],
    ) -> str:
        fallback = distinct_query(question, previous_query)
        if not llm.is_configured():
            return fallback
        hit_block = (
            f"\n上次命中（不切题）：\n{summarize_hits(hits, 3)}"
            if hits
            else "\n上次无命中。"
        )
        try:
            parsed = await llm.chat_json(
                RETRY_REWRITE_PROMPT + RETRY_OUTPUT_HINT,
                (
                    f"用户问题：{question}\n上次检索词：{previous_query}\n"
                    f"不足原因：{grade.text}{hit_block}"
                ),
            )
            candidate = str((parsed or {}).get("query") or "").strip()
            query = distinct_query(candidate, previous_query)
            if query:
                logger.info(
                    "检索改写：%s → %s", previous_query[:40], query[:40]
                )
                return query
            return fallback
        except Exception as exc:  # pragma: no cover - 外部模型
            logger.warning("检索改写失败，回退原问题：%s", exc)
            return fallback

    def _to_plan(
        self,
        intent: str,
        query: str,
        graph_queries: list[str] | None = None,
    ) -> ChatRoutePlan:
        kb = intent in ("kb", "kb_then_web")
        return ChatRoutePlan(
            intent=intent,
            label=INTENT_LABEL.get(intent, INTENT_LABEL["kb"]),
            query=query,
            graph_queries=[
                item.strip() for item in (graph_queries or []) if item.strip()
            ]
            if kb
            else [],
            allow_retrieve=kb,
            allow_graph=kb,
            allow_web=intent in ("web", "kb_then_web"),
        )


def compact_rewrite_context(history: list[dict[str, str]]) -> str:
    """给检索改写器用：最近几轮，助手只留短摘要。"""
    if not history:
        return ""
    lines: list[str] = []
    for message in history[-4:]:
        text = (message.get("content") or "").strip()
        if not text:
            continue
        if message.get("role") == "user":
            lines.append(f"用户：{text[:200]}")
        elif message.get("role") == "assistant":
            lines.append(f"助手：{text[:120]}")
    return "\n".join(lines)


def summarize_hits(hits: list[dict[str, Any]], limit: int = 5) -> str:
    lines: list[str] = []
    for index, hit in enumerate(hits[:limit]):
        heading = f" / {hit['heading']}" if hit.get("heading") else ""
        snippet = re.sub(r"\s+", " ", str(hit.get("content") or "")).strip()[:180]
        score = hit.get("score")
        score_text = f"{score:.2f}" if isinstance(score, (int, float)) else "-"
        lines.append(
            f"{index + 1}. {hit.get('documentTitle') or ''}{heading}"
            f"（分={score_text}）\n{snippet}"
        )
    return "\n".join(lines)


def distinct_query(next_query: str, previous: str) -> str:
    query = re.sub(r"\s+", " ", next_query).strip()
    if not query:
        return ""
    if query == re.sub(r"\s+", " ", previous).strip():
        return ""
    return query


query_rewrite = ChatQueryRewrite()
