"""配置读写路由：对应原 AppConfig.cs 的 ConfigData。"""
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..config import config
from ..deps import require_auth

router = APIRouter(prefix="/api/settings", tags=["settings"], dependencies=[Depends(require_auth)])


class SettingsIn(BaseModel):
    notion_token: str | None = None
    notion_base_url: str | None = None
    max_download_workers: int | None = None
    max_upload_workers: int | None = None
    enable_range_download: bool | None = None
    range_download_min_mb: int | None = None
    range_download_chunks: int | None = None
    cache_auto_cleanup_enabled: bool | None = None
    cache_ttl_seconds: int | None = None
    cache_cleanup_interval_seconds: int | None = None
    theme_accent_color: str | None = None
    background: str | None = None
    password: str | None = None
    # 注意：channel 仅由环境变量 NFM_CHANNEL 决定，不通过 Web 修改


@router.get("")
async def get_settings():
    return config.public_dict


@router.put("")
async def put_settings(body: SettingsIn):
    patch = body.model_dump(exclude_none=True)
    for k, v in patch.items():
        if v is not None:
            config[k] = v
    config.save()
    return {"ok": True}
