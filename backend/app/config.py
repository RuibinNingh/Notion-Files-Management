"""应用配置：环境变量 + 持久化 config.json。
对应原 AppConfig.cs 的 ConfigData / ConfigManager。
"""
import json
import os
import secrets
from pathlib import Path

from .app_version import DEFAULT_CHANNEL, VALID_CHANNELS

DATA_DIR = Path(os.environ.get("NFM_DATA_DIR", Path.home() / ".notion-files-management"))
CONFIG_PATH = DATA_DIR / "config.json"
STAGING_DIR = DATA_DIR / "staging"
LOG_DIR = DATA_DIR / "logs"
NOTICES_CACHE = DATA_DIR / "notices_cache"

_DEFAULTS = {
    "secret_key": "",
    "password": "",
    "notion_token": "",
    "notion_base_url": "https://api.notion.com/v1",
    "max_download_workers": 3,
    "max_upload_workers": 3,
    "enable_range_download": False,
    "range_download_min_mb": 128,
    "range_download_chunks": 4,
    "cache_auto_cleanup_enabled": True,
    "cache_ttl_seconds": 3600,
    "cache_cleanup_interval_seconds": 900,
    "theme_accent_color": "#1E90FF",
    "background": "",
    "channel": DEFAULT_CHANNEL,
}


class Config:
    def __init__(self):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._d = dict(_DEFAULTS)
        self.load()
        self._bootstrap()

    def load(self):
        if CONFIG_PATH.exists():
            try:
                self._d.update(json.loads(CONFIG_PATH.read_text("utf-8")))
            except Exception:
                pass
        # 环境变量覆盖（部署用）
        for k in ("secret_key", "password", "notion_token", "notion_base_url"):
            v = os.environ.get("NFM_" + k.upper())
            if v:
                self._d[k] = v
        for k in ("max_download_workers", "max_upload_workers",
                  "range_download_min_mb", "range_download_chunks",
                  "cache_ttl_seconds", "cache_cleanup_interval_seconds"):
            v = os.environ.get("NFM_" + k.upper())
            if v and str(v).isdigit():
                self._d[k] = int(v)
        v = os.environ.get("NFM_ENABLE_RANGE_DOWNLOAD")
        if v:
            self._d["enable_range_download"] = v.lower() in ("1", "true", "yes", "on")
        v = os.environ.get("NFM_CACHE_AUTO_CLEANUP_ENABLED")
        if v:
            self._d["cache_auto_cleanup_enabled"] = v.lower() in ("1", "true", "yes", "on")
        # 渠道覆盖：env 优先（启动参数或构建产物写死），其次 config.json
        ch = os.environ.get("NFM_CHANNEL", "").strip()
        if ch in VALID_CHANNELS:
            self._d["channel"] = ch
        elif self._d.get("channel") not in VALID_CHANNELS:
            self._d["channel"] = DEFAULT_CHANNEL

    def save(self):
        CONFIG_PATH.write_text(json.dumps(self._d, indent=2, ensure_ascii=False), "utf-8")

    def _bootstrap(self):
        changed = False
        if not self._d["secret_key"]:
            self._d["secret_key"] = secrets.token_hex(32)
            changed = True
        if not self._d["password"]:
            self._d["password"] = secrets.token_urlsafe(12)
            changed = True
        # 渠道持久化：首次启动写入 channel，后续 env 覆盖立即生效
        if "channel" not in self._d or self._d["channel"] not in VALID_CHANNELS:
            self._d["channel"] = DEFAULT_CHANNEL
            changed = True
        if changed:
            self.save()
            print("=" * 60, flush=True)
            print("NFM 初始登录密码（请妥善保存，可在设置页修改）：", self._d["password"], flush=True)
            print(f"NFM 当前渠道：{self._d['channel']}", flush=True)
            print("=" * 60, flush=True)

    def __getitem__(self, k):
        return self._d[k]

    def __setitem__(self, k, v):
        self._d[k] = v

    def as_dict(self):
        return dict(self._d)

    @property
    def public_dict(self):
        """对外可见配置（剔除 secret_key / password）。"""
        d = self.as_dict()
        d.pop("secret_key", None)
        d.pop("password", None)
        return d

    @property
    def channel(self) -> str:
        return self._d.get("channel") or DEFAULT_CHANNEL


config = Config()
