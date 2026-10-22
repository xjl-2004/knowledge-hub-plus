from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.deps import CurrentUser, require_permissions
from app.pipeline import graph_build
from app.schemas.graph import (
    GraphOverviewDto,
    GraphQueryDto,
    GraphSearchDto,
)
from app.services.documents import access_from_user

router = APIRouter(prefix="/graph", tags=["graph"])
search_permission = [Depends(require_permissions("search"))]


@router.get("/overview", dependencies=search_permission)
async def get_overview(
    user: CurrentUser,
    query: Annotated[GraphOverviewDto, Depends()],
):
    """图谱全景概览，供前端力导向图。"""
    return await graph_build.get_overview(
        {
            "keyword": query.keyword,
            "entity_type": query.entity_type,
            "from": query.from_date,
            "to": query.to_date,
            "doc_limit": query.doc_limit,
        },
        access_from_user(user),
    )


@router.get("/search", dependencies=search_permission)
async def search_graph(
    user: CurrentUser,
    query: Annotated[GraphSearchDto, Depends()],
):
    """关键词检索图谱节点。"""
    return await graph_build.search_graph(
        query.keyword, query.limit, access_from_user(user)
    )


@router.get("/nodes", dependencies=search_permission)
async def list_nodes(
    user: CurrentUser,
    query: Annotated[GraphQueryDto, Depends()],
):
    """列出知识实体节点。"""
    return await graph_build.list_nodes(
        query.type, query.limit, access_from_user(user)
    )


@router.get("/edges", dependencies=search_permission)
async def list_edges(
    user: CurrentUser,
    query: Annotated[GraphQueryDto, Depends()],
):
    """列出实体之间的关系边。"""
    return await graph_build.list_edges(query.limit, access_from_user(user))
