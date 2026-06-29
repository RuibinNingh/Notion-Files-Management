"""短期 SSE token：浏览器 EventSource 不能自定义请求头，长期 API Key 又不该出现在 URL 里。

折中：第三方先用 Bearer API Key（带 ``tasks`` scope）或 session 调
``POST /api/tasks/{tid}/events-token`` 换一个 10 分钟有效的 ``nfmsse_...`` token，
再用 ``?events_token=...`` 订阅 ``/api/tasks/{tid}/events``。

- 进程内存储，服务重启失效（可接受）。
- 绑定单个 ``task_id``，换任务即失效。
- 不记录创建它的 API key/session 内容，只记一个标记用于审计展示。
"""
from __future__ import annotations

import secrets
import threading
import time

TOKEN_PREFIX = "nfmsse_"
TTL_SECONDS = 600  # 10 分钟

_lock = threading.RLock()
# token -> {"task_id": str, "created_by": str, "expires_at": float}
_tokens: dict[str, dict] = {}


def _now() -> float:
    return time.monotonic()


def create(task_id: str, created_by: str = "") -> tuple[str, int]:
    """为 ``task_id`` 签发一个短期 token，返回 (token, expires_in)。"""
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    expires_at = time.time() + TTL_SECONDS
    with _lock:
        _tokens[token] = {
            "task_id": task_id,
            "created_by": created_by[:64],
            "expires_at": expires_at,
        }
        _cleanup_locked()
    return token, TTL_SECONDS


def verify(token: str, task_id: str) -> bool:
    """校验 token 是否有效且绑定到 ``task_id``。过期的会顺手清除。"""
    if not token or not token.startswith(TOKEN_PREFIX):
        return False
    with _lock:
        rec = _tokens.get(token)
        if rec is None:
            return False
        if rec["expires_at"] <= time.time():
            _tokens.pop(token, None)
            return False
        return rec["task_id"] == task_id


def _cleanup_locked() -> None:
    now = time.time()
    for k in list(_tokens):
        if _tokens[k]["expires_at"] <= now:
            del _tokens[k]


def clear() -> None:
    """测试用：清空所有 token。"""
    with _lock:
        _tokens.clear()
