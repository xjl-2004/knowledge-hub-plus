import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)

Message = str | list[str]


class ApiError(Exception):
    def __init__(self, status_code: int, message: Message) -> None:
        super().__init__(message if isinstance(message, str) else "; ".join(message))
        self.status_code = status_code
        self.message: Message = message


def bad_request(message: Message = "请求参数错误") -> ApiError:
    return ApiError(400, message)


def unauthorized(message: str = "未授权") -> ApiError:
    return ApiError(401, message)


def forbidden(message: str = "无权限") -> ApiError:
    return ApiError(403, message)


def not_found(message: str = "资源不存在") -> ApiError:
    return ApiError(404, message)


def conflict(message: str) -> ApiError:
    return ApiError(409, message)


def unavailable(message: str) -> ApiError:
    return ApiError(503, message)


def _format_errors(errors: list[dict[str, Any]]) -> list[str]:
    messages: list[str] = []
    for item in errors:
        loc = [part for part in item.get("loc", []) if part not in ("body", "query", "path")]
        field = ".".join(str(part) for part in loc)
        msg = str(item.get("msg", "取值非法"))
        messages.append(f"{field} {msg}" if field else msg)
    return messages or ["请求参数错误"]


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"message": exc.message})

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=400,
            content={"message": _format_errors(list(exc.errors()))},
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail
        if isinstance(detail, list):
            message: Message = [str(item) for item in detail]
        elif isinstance(detail, dict):
            message = str(detail.get("message") or detail)
        else:
            message = str(detail or "请求失败")
        return JSONResponse(status_code=exc.status_code, content={"message": message})

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("未处理异常 %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"message": "服务器内部错误"})
