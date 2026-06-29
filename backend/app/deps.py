"""鉴权依赖：双通道。

1. 浏览器：签名 Session Cookie（``req.session['auth']``）—— 管理员全权限。
2. 第三方：``Authorization: Bearer nfm_...``。**长期 API Key 永远只走 Bearer 头**，
   不接受 URL query 参数（避免明文进访问日志/Referer）。

唯一例外是 SSE：浏览器 ``EventSource`` 不能自定义请求头，所以用短期
``nfmsse_...`` token（见 ``ssetokens``）走 ``?events_token=``，绑定单个 task、
10 分钟有效。``?api_key=`` 已废弃，任何接口都不再接受。

统一返回：未认证 401，权限不足 403，限流超限 429，禁用/过期/伪造 key 一律 401。

scope 是粗粒度功能分组（见 ``apikeys.ALL_SCOPES``）。session 登录始终通过所有 scope
校验；API key 必须显式持有对应 scope。路由用 ``require_scope("scan")`` 声明所需权限。
"""
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from .apikeys import verify_key, record_usage, check_rate_limit
from . import ssetokens

_bearer = HTTPBearer(auto_error=False)


def _client_ip(request: Request) -> str:
    try:
        return request.client.host if request.client else ""
    except Exception:
        return ""


def _bearer_token(credentials: HTTPAuthorizationCredentials | None) -> str | None:
    """仅从 Authorization: Bearer 头取 token。不接受 query 参数。"""
    if credentials and credentials.scheme.lower() == "bearer" and credentials.credentials:
        return credentials.credentials
    return None


def resolve_auth(request: Request, credentials: HTTPAuthorizationCredentials | None) -> None:
    """解析当前请求的鉴权身份（session 或 Bearer API Key），结果写入 ``request.state``。

    - ``auth_mode``: "session" | "apikey"
    - ``auth_scopes``: set[str]（session 为 None，表示管理员，跳过 scope 校验）
    - ``auth_key_id``: API key 模式下的 key id
    """
    # 1) session 浏览器登录：管理员，全权限
    if request.session.get("auth"):
        request.state.auth_mode = "session"
        request.state.auth_scopes = None
        request.state.auth_key_id = None
        return

    # 2) API Key（仅 Bearer 头）
    token = _bearer_token(credentials)
    if not token:
        raise HTTPException(status_code=401, detail="未登录或缺少 API Key")
    rec = verify_key(token)
    if rec is None:
        raise HTTPException(status_code=401, detail="API Key 无效、已禁用或已过期")

    # 限流（429）
    if not check_rate_limit(rec):
        raise HTTPException(status_code=429, detail="API Key 请求过于频繁，请稍后再试")

    record_usage(rec, _client_ip(request))
    request.state.auth_mode = "apikey"
    request.state.auth_scopes = set(rec.get("scopes", []))
    request.state.auth_key_id = rec.get("id")


def require_auth(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> bool:
    """只要「已登录」（session 或任意有效 key）即可。不校验 scope。"""
    resolve_auth(request, credentials)
    return True


def require_scope(*scopes: str):
    """要求当前身份持有给定 scope 之一即可（session 管理员免校验）。

    用法：``dependencies=[Depends(require_scope("scan"))]``
    """
    needed = set(scopes)

    def _dep(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> bool:
        resolve_auth(request, credentials)
        if getattr(request.state, "auth_mode", None) == "session":
            return True
        granted = getattr(request.state, "auth_scopes", set()) or set()
        if needed and not (needed & granted):
            raise HTTPException(status_code=403, detail="API Key 缺少所需权限: " + ",".join(sorted(needed)))
        return True

    _dep.__name__ = f"require_scope_{'_'.join(scopes) or 'any'}"
    return _dep


def require_events_access(tid: str, request: Request,
                          credentials: HTTPAuthorizationCredentials | None = Depends(_bearer)) -> bool:
    """SSE 事件流专用鉴权，三选一：

    1. session 浏览器登录（管理员）
    2. Bearer API Key 且持有 ``tasks`` scope
    3. ``?events_token=nfmsse_...`` 短期 token，且绑定到本 ``tid``

    不接受 ``?api_key=``。
    """
    # 1) session
    if request.session.get("auth"):
        return True

    # 2) Bearer API Key（需 tasks scope）
    token = _bearer_token(credentials)
    if token:
        rec = verify_key(token)
        if rec is None:
            raise HTTPException(status_code=401, detail="API Key 无效、已禁用或已过期")
        if not check_rate_limit(rec):
            raise HTTPException(status_code=429, detail="API Key 请求过于频繁，请稍后再试")
        record_usage(rec, _client_ip(request))
        if "tasks" not in set(rec.get("scopes", [])):
            raise HTTPException(status_code=403, detail="API Key 缺少所需权限: tasks")
        return True

    # 3) 短期 SSE token
    et = request.query_params.get("events_token")
    if et:
        if not ssetokens.verify(et, tid):
            raise HTTPException(status_code=401, detail="SSE token 无效、已过期或与任务不匹配")
        return True

    raise HTTPException(status_code=401, detail="未登录或缺少 API Key")
