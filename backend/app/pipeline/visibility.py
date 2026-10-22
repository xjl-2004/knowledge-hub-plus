"""Elasticsearch 可见性过滤条件。"""

from typing import Any

# kh_document 使用 camelCase，kh_chunk 使用 snake_case
ES_DOC_VISIBILITY_FIELDS = {
    "isPublic": "isPublic",
    "authorId": "authorId",
    "teamId": "teamId",
}

ES_CHUNK_VISIBILITY_FIELDS = {
    "isPublic": "is_public",
    "authorId": "author_id",
    "teamId": "team_id",
}


def es_visibility_filter(
    scope: Any,
    fields: dict[str, str],
) -> dict[str, Any] | None:
    """公开 ∪ 自己写的 ∪ 所在团队；管理员/审核员不加过滤。"""
    if scope is None or scope.unrestricted:
        return None

    should: list[dict[str, Any]] = [
        {"term": {fields["isPublic"]: True}},
        {"term": {fields["authorId"]: scope.user_id}},
    ]
    if scope.team_ids:
        should.append({"terms": {fields["teamId"]: list(scope.team_ids)}})
    return {"bool": {"should": should, "minimum_should_match": 1}}


def wrap_es_query(
    query: dict[str, Any],
    filter_clause: dict[str, Any] | None,
) -> dict[str, Any]:
    """相关性查询放 must，可见性条件放 filter，避免影响打分。"""
    if filter_clause is None:
        return query
    return {"bool": {"must": [query], "filter": [filter_clause]}}


def neo4j_access_params(scope: Any = None) -> dict[str, Any]:
    return {
        "unrestricted": scope is None or scope.unrestricted,
        "accessUserId": scope.user_id if scope else "",
        "accessTeamIds": list(scope.team_ids) if scope else [],
    }


def neo4j_document_access_where(alias: str = "d") -> str:
    """Cypher：文档节点是否对当前用户可见。"""
    return (
        f"($unrestricted OR {alias}.authorId = $accessUserId "
        f"OR {alias}.isPublic = true OR {alias}.teamId IN $accessTeamIds)"
    )
