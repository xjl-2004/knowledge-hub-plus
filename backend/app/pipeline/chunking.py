"""Markdown 感知的递归分块。

将正文按标题 / 代码块 / 段落逐级切分，再按 chunkSize / chunkOverlap 合并，
并为每块补上所属章节标题，便于检索命中时保留上下文。
"""

import hashlib
import logging
import re

from app.core.config import settings
from app.pipeline.types import DocumentChunk

logger = logging.getLogger(__name__)

# 中英文混合场景下约 1 token ≈ 2 字符
CHARS_PER_TOKEN = 2.0

HEADING_LINE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)

# 由粗到细的分隔符；末尾空字符串表示退化为按字符切分
SEPARATORS: tuple[str, ...] = (
    r"\n#{1,6} ",
    r"```\n",
    r"\n\*\*\*+\n",
    r"\n---+\n",
    r"\n___+\n",
    r"\n\n",
    r"\n",
    r" ",
    "",
)


def _split_keep_separator(text: str, separator: str) -> list[str]:
    """按分隔符切分，并把分隔符附到后一段开头。"""
    if separator == "":
        return list(text)

    pieces: list[str] = []
    pending = ""
    last = 0
    for match in re.finditer(separator, text):
        segment = text[last : match.start()]
        if segment:
            pieces.append(pending + segment)
            pending = ""
        pending += match.group(0)
        last = match.end()

    tail = text[last:]
    if tail or pending:
        pieces.append(pending + tail)
    return [piece for piece in pieces if piece]


def _split_recursive(text: str, separators: tuple[str, ...], chunk_size: int) -> list[str]:
    """递归挑选能命中文本的最细分隔符，直到每段都不超过 chunk_size。"""
    if not text:
        return []

    separator = separators[-1]
    remaining: tuple[str, ...] = ()
    for index, candidate in enumerate(separators):
        if candidate == "":
            separator = ""
            break
        if re.search(candidate, text):
            separator = candidate
            remaining = separators[index + 1 :]
            break

    pieces = _split_keep_separator(text, separator)
    if separator == "":
        return pieces

    result: list[str] = []
    for piece in pieces:
        if len(piece) <= chunk_size:
            result.append(piece)
        else:
            result.extend(_split_recursive(piece, remaining, chunk_size))
    return result


def _merge_splits(splits: list[str], chunk_size: int, chunk_overlap: int) -> list[str]:
    """把细碎片段合并到目标长度，并在相邻块之间保留重叠。"""
    docs: list[str] = []
    current: list[str] = []
    total = 0

    for piece in splits:
        length = len(piece)
        if current and total + length > chunk_size:
            merged = "".join(current).strip()
            if merged:
                docs.append(merged)
            while total > chunk_overlap or (
                total + length > chunk_size and total > 0
            ):
                total -= len(current[0])
                current.pop(0)

        current.append(piece)
        total += length

    merged = "".join(current).strip()
    if merged:
        docs.append(merged)
    return docs


def _extract_heading(text: str) -> str | None:
    match = HEADING_LINE.search(text)
    if match is None:
        return None
    heading = match.group(2).strip()
    return heading or None


async def chunk(
    content: str,
    document_id: str,
    document_title: str,
    *,
    category_id: str | None = None,
    author_id: str | None = None,
    team_id: str | None = None,
    is_public: bool = False,
    doc_status: int | None = None,
    publish_time: str | None = None,
) -> list[DocumentChunk]:
    """将 Markdown 正文切成可索引的块；内容为空时返回空列表。"""
    if not content or not content.strip():
        logger.warning("文档内容为空，跳过分块：documentId=%s", document_id)
        return []

    chunk_size = max(1, int(settings.rag_chunk_size * CHARS_PER_TOKEN))
    chunk_overlap = max(0, int(settings.rag_chunk_overlap * CHARS_PER_TOKEN))

    splits = _split_recursive(content, SEPARATORS, chunk_size)
    texts = _merge_splits(splits, chunk_size, chunk_overlap)

    chunks: list[DocumentChunk] = []
    current_heading: str | None = None

    for text in texts:
        trimmed = text.strip()
        if not trimmed:
            continue

        heading_in_chunk = _extract_heading(trimmed)
        if heading_in_chunk:
            current_heading = heading_in_chunk

        # 同章节后续块通常不含标题行，补上以便检索时带上下文
        chunk_content = trimmed
        if current_heading and not HEADING_LINE.search(trimmed):
            chunk_content = f"{current_heading}\n\n{trimmed}"

        chunk_id = hashlib.sha256(
            f"{document_id}:{len(chunks)}".encode("utf-8")
        ).hexdigest()[:64]
        chunks.append(
            DocumentChunk(
                chunk_id=chunk_id,
                document_id=document_id,
                document_title=document_title,
                content=chunk_content,
                heading=current_heading,
                chunk_index=len(chunks),
                total_chunks=0,
                category_id=category_id,
                author_id=author_id,
                team_id=team_id,
                is_public=is_public,
                doc_status=doc_status,
                publish_time=publish_time,
            )
        )

    total = len(chunks)
    for item in chunks:
        item.total_chunks = total

    logger.debug(
        "文档分块完成：documentId=%s, totalChunks=%s", document_id, total
    )
    return chunks
