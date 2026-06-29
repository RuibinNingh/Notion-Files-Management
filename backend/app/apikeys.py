"""第三方开放 API 的 API Key 管理。

存储落在 ``config.json`` 的 ``api_keys`` 列表里，**只保存 hash**，不保存明文。
创建时只返回一次明文，之后只能查看前缀、名称、权限、状态、过期、限流、最后使用。

设计要点：
- 单租户：所有 key 共享同一个 Notion Token，key 只是「能不能调这个 Web 的接口」的凭据。
- scope 是粗粒度功能分组，session 登录的浏览器始终是全权限管理员。
- 限流是进程内滑动窗口（每分钟请求数），0 表示不限。多进程部署下各自计数（已知限制）。
- ``last_used`` 写盘做了 60s 节流，避免每次调用都写 config.json。
"""
from __future__ import annotations

import hashlib
import os
import secrets
import threading
from datetime import datetime, timedelta, timezone

from .config import config

try:  # bootstrap 弱 key 警告走项目 logger
    from logger import PythonLogger as _Log  # noqa: E402
except Exception:  # pragma: no cover - logger 在 scripts sys.path 上
    class _Log:  # type: ignore
        @staticmethod
        def warning(msg: str) -> None:
            print(f"[WARN] {msg}")

# 权限范围（scope）。前 5 个是任务型业务能力；后 5 个是高危能力，需显式授权。
BUSINESS_SCOPES = ("scan", "download", "upload", "tools", "tasks")
HIGH_RISK_SCOPES = ("settings", "system", "logs", "cache", "apikeys")
ALL_SCOPES = BUSINESS_SCOPES + HIGH_RISK_SCOPES
_ALL_SET = set(ALL_SCOPES)

KEY_PREFIX = "nfm_"
# 明文展示用的前缀：KEY_PREFIX + 8 位
PREFIX_DISPLAY_LEN = len(KEY_PREFIX) + 8

_lock = threading.RLock()
# key_id -> 最近一次 last_used 写盘时间（节流用）
_last_used_write: dict[str, float] = {}
# key_id -> 滑动窗口内的请求时间戳列表（限流用）
_rate_buckets: dict[str, list[float]] = {}

# update_key 用：区分「字段未传」与「显式传 None（清空过期时间）」
_UNSET = object()

# bootstrap 预置 key 的最小有效负载长度（nfm_ 之后部分）
_MIN_BOOTSTRAP_PAYLOAD = 32


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_ts() -> float:
    return _now().timestamp()


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def generate_plaintext() -> str:
    """生成一条明文 key：``nfm_<32 字节 urlsafe>``。"""
    return KEY_PREFIX + secrets.token_urlsafe(32)


def hash_key(plaintext: str) -> str:
    """sha256 十六进制摘要。明文不落盘。"""
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def prefix_of(plaintext: str) -> str:
    """明文展示前缀，用于列表里识别（不泄露完整 key）。"""
    return plaintext[:PREFIX_DISPLAY_LEN]


def _records() -> list[dict]:
    recs = config["api_keys"]
    if not isinstance(recs, list):
        config["api_keys"] = []
        return config["api_keys"]
    return recs


def _persist():
    config.save()


def _sanitize(rec: dict) -> dict:
    """去掉 hash，返回对外安全的副本。"""
    out = dict(rec)
    out.pop("hash", None)
    return out


def list_keys() -> list[dict]:
    with _lock:
        return [_sanitize(r) for r in _records()]


def get_key(key_id: str) -> dict | None:
    with _lock:
        for r in _records():
            if r.get("id") == key_id:
                return _sanitize(r)
    return None


def _normalize_scopes(scopes) -> list[str]:
    """严格校验 scope：去重、小写；遇到未知 scope 直接抛 ValueError（不静默过滤）。"""
    out: list[str] = []
    for s in scopes or []:
        s = str(s).strip().lower()
        if not s:
            continue
        if s not in _ALL_SET:
            raise ValueError(f"未知 scope: {s}")
        if s not in out:
            out.append(s)
    return out


def _parse_expires(expires_at) -> datetime | None:
    if expires_at in (None, "", "never"):
        return None
    if isinstance(expires_at, datetime):
        return expires_at if expires_at.tzinfo else expires_at.replace(tzinfo=timezone.utc)
    s = str(expires_at).strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        raise ValueError("过期时间格式无效，需为 ISO 8601 或留空")


def create_key(*, name: str, scopes, expires_at=None, rate_limit_rpm: int = 0,
               enabled: bool = True) -> tuple[dict, str]:
    """创建一条 key。返回 (对外记录, 明文)。明文只此一次返回。"""
    norm = _normalize_scopes(scopes)
    if not norm:
        raise ValueError("至少需要授权一个 scope")
    exp = _parse_expires(expires_at)
    plaintext = generate_plaintext()
    rec = {
        "id": "k_" + secrets.token_hex(6),
        "name": (name or "").strip()[:120] or "未命名",
        "prefix": prefix_of(plaintext),
        "hash": hash_key(plaintext),
        "scopes": norm,
        "enabled": bool(enabled),
        "expires_at": _iso(exp),
        "rate_limit_rpm": max(0, int(rate_limit_rpm or 0)),
        "created_at": _iso(_now()),
        "last_used_at": None,
        "last_used_ip": "",
    }
    with _lock:
        _records().append(rec)
        _persist()
    return _sanitize(rec), plaintext


def update_key(key_id: str, *, name=_UNSET, scopes=_UNSET, enabled=_UNSET,
               expires_at=_UNSET, rate_limit_rpm=_UNSET) -> dict | None:
    """更新一条 key。用 ``_UNSET`` 哨兵区分「字段未传」与「显式传 None」。

    特别地，``expires_at=None`` 会**清空**过期时间（设为永不过期）。
    未知 scope / 空 scope / 非法过期时间抛 ValueError，由路由转 400。
    """
    with _lock:
        for r in _records():
            if r.get("id") == key_id:
                if name is not _UNSET and name is not None:
                    r["name"] = (str(name).strip() or r["name"])[:120]
                if scopes is not _UNSET:
                    norm = _normalize_scopes(scopes)
                    if not norm:
                        raise ValueError("至少需要授权一个 scope")
                    r["scopes"] = norm
                if enabled is not _UNSET and enabled is not None:
                    r["enabled"] = bool(enabled)
                if expires_at is not _UNSET:
                    # 显式传 None → 清空过期；传字符串 → 解析为 UTC ISO
                    r["expires_at"] = _iso(_parse_expires(expires_at))
                if rate_limit_rpm is not _UNSET and rate_limit_rpm is not None:
                    r["rate_limit_rpm"] = max(0, int(rate_limit_rpm or 0))
                _persist()
                return _sanitize(r)
    return None


def delete_key(key_id: str) -> bool:
    with _lock:
        recs = _records()
        for i, r in enumerate(recs):
            if r.get("id") == key_id:
                del recs[i]
                _persist()
                _last_used_write.pop(key_id, None)
                _rate_buckets.pop(key_id, None)
                return True
    return False


def _is_expired(rec: dict) -> bool:
    s = rec.get("expires_at")
    if not s:
        return False
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return _now() >= dt


def verify_key(plaintext: str) -> dict | None:
    """校验明文 key。通过返回记录（含 id/scopes），否则 None。

    会顺带做启停、过期检查，并节流地更新 last_used。hash 比较用
    ``secrets.compare_digest`` 做常量时间比较。
    """
    if not plaintext or not plaintext.startswith(KEY_PREFIX):
        return None
    h = hash_key(plaintext)
    with _lock:
        for r in _records():
            stored = r.get("hash")
            if stored and secrets.compare_digest(h, stored):
                if not r.get("enabled", True):
                    return None
                if _is_expired(r):
                    return None
                return r
    return None


def record_usage(rec: dict, client_ip: str = "") -> None:
    """节流地写 last_used（每 60s 最多落盘一次）。"""
    key_id = rec.get("id")
    if not key_id:
        return
    now = _now_ts()
    last = _last_used_write.get(key_id, 0.0)
    if now - last < 60:
        return
    _last_used_write[key_id] = now
    with _lock:
        for r in _records():
            if r.get("id") == key_id:
                r["last_used_at"] = _iso(_now())
                if client_ip:
                    r["last_used_ip"] = client_ip[:64]
                _persist()
                return


def check_rate_limit(rec: dict) -> bool:
    """滑动窗口限流。返回 True=未超限，False=超限。0 表示不限。"""
    rpm = int(rec.get("rate_limit_rpm", 0) or 0)
    if rpm <= 0:
        return True
    key_id = rec.get("id")
    if not key_id:
        return True
    now = _now_ts()
    window = 60.0
    with _lock:
        bucket = _rate_buckets.setdefault(key_id, [])
        # 丢弃窗口外
        cutoff = now - window
        bucket[:] = [t for t in bucket if t > cutoff]
        if len(bucket) >= rpm:
            return False
        bucket.append(now)
        return True


def bootstrap_preset_key() -> None:
    """从 ``NFM_BOOTSTRAP_API_KEY`` 预置一条全权限 key（以 hash 落盘）。

    严格要求：必须是 ``nfm_`` 前缀，且前缀之后的有效负载长度 ≥ 32 字符。
    不合格则忽略并记录 warning，**不**自动补前缀（避免把弱值包装成 key）。
    重复启动不重复创建（按前缀/hash 去重）。
    """
    plaintext = os.environ.get("NFM_BOOTSTRAP_API_KEY", "").strip()
    if not plaintext:
        return
    if not plaintext.startswith(KEY_PREFIX):
        _Log.warning(
            f"NFM_BOOTSTRAP_API_KEY 缺少 '{KEY_PREFIX}' 前缀，已忽略，未预置 API Key"
        )
        return
    payload = plaintext[len(KEY_PREFIX):]
    if len(payload) < _MIN_BOOTSTRAP_PAYLOAD:
        _Log.warning(
            f"NFM_BOOTSTRAP_API_KEY 有效负载过短（{len(payload)} < {_MIN_BOOTSTRAP_PAYLOAD}），"
            "已忽略，未预置 API Key"
        )
        return
    pref = prefix_of(plaintext)
    h = hash_key(plaintext)
    with _lock:
        for r in _records():
            if r.get("prefix") == pref or (r.get("hash") and secrets.compare_digest(h, r["hash"])):
                return  # 已存在，不重复创建
        rec = {
            "id": "k_" + secrets.token_hex(6),
            "name": "bootstrap",
            "prefix": pref,
            "hash": h,
            "scopes": list(ALL_SCOPES),
            "enabled": True,
            "expires_at": None,
            "rate_limit_rpm": 0,
            "created_at": _iso(_now()),
            "last_used_at": None,
            "last_used_ip": "",
        }
        _records().append(rec)
        _persist()


def status_of(rec: dict) -> str:
    """给前端展示用的状态：active / disabled / expired。"""
    if not rec.get("enabled", True):
        return "disabled"
    if _is_expired(rec):
        return "expired"
    return "active"
