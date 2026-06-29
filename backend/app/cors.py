"""动态 CORS 中间件。

与 starlette 的 ``CORSMiddleware`` 不同，本中间件**每次请求**实时读取
``config["api_cors_allowed_origins"]``，所以改设置后无需重启即生效。

规则：
- 默认白名单为空 = 完全不开放跨域。
- 仅允许 ``http://`` / ``https://`` origin；拒绝 ``*``、``null``、带 path/query 的值。
- 不允许 ``*`` 搭配凭据（本中间件始终 ``allow_credentials=true``，所以 ``*`` 永不放行）。
- OPTIONS preflight 只对白名单 origin 返回 CORS 头；否则透传给应用。
- 非白名单 origin 的普通请求不附加 CORS 头（浏览器自动拦截）。
"""
from __future__ import annotations

from urllib.parse import urlparse

from starlette.datastructures import Headers

# 允许的方法/头与原 CORSMiddleware 配置保持一致
_METHODS = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
_HEADERS = "Authorization, Content-Type, Accept"
_MAX_AGE = "600"


def is_valid_origin(origin: str) -> bool:
    """校验单个 origin 是否合法：仅 http/https、有 host、无 path/query/fragment。"""
    if not origin or origin in ("*", "null"):
        return False
    try:
        p = urlparse(origin)
    except Exception:
        return False
    if p.scheme not in ("http", "https"):
        return False
    if not p.netloc:
        return False
    if p.path not in ("", "/"):
        return False
    if p.query or p.params or p.fragment:
        return False
    return True


def _allowed_origins() -> set[str]:
    """实时读取并校验白名单（非法值静默丢弃）。"""
    from .config import config  # 延迟导入避免循环
    raw = config["api_cors_allowed_origins"] or []
    if not isinstance(raw, list):
        return set()
    return {str(o).strip() for o in raw if is_valid_origin(str(o).strip())}


def _cors_headers(origin: str) -> dict[str, str]:
    return {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Credentials": "true",
        "Vary": "Origin",
    }


class DynamicCORSMiddleware:
    """ASGI 中间件：动态白名单 CORS。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        origin = headers.get("origin")
        allowed = _allowed_origins()
        is_allowed = bool(origin) and origin in allowed

        is_preflight = (
            scope["method"] == "OPTIONS"
            and bool(headers.get("access-control-request-method"))
        )

        if is_preflight:
            if is_allowed:
                resp_headers = _cors_headers(origin)
                resp_headers["Access-Control-Allow-Methods"] = _METHODS
                resp_headers["Access-Control-Allow-Headers"] = _HEADERS
                resp_headers["Access-Control-Max-Age"] = _MAX_AGE
                await self._send_empty(send, 200, resp_headers)
            else:
                # 非白名单 preflight：透传给应用（无 CORS 头，浏览器拦截）
                await self.app(scope, receive, send)
            return

        if is_allowed:
            async def send_wrapper(message):
                if message["type"] == "http.response.start":
                    new_headers = list(message.get("headers") or [])
                    for k, v in _cors_headers(origin).items():
                        new_headers.append((k.encode("latin-1"), v.encode("latin-1")))
                    message = dict(message)
                    message["headers"] = new_headers
                await send(message)

            await self.app(scope, receive, send_wrapper)
        else:
            await self.app(scope, receive, send)

    @staticmethod
    async def _send_empty(send, status: int, headers: dict[str, str]) -> None:
        raw = [(k.encode("latin-1"), v.encode("latin-1")) for k, v in headers.items()]
        await send({"type": "http.response.start", "status": status, "headers": raw})
        await send({"type": "http.response.body", "body": b""})
