"""配置读写路由：对应原 AppConfig.cs 的 ConfigData。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..config import config
from ..deps import require_auth
from url_security import UnsafeUrlError, assert_safe_remote_url

router = APIRouter(prefix="/api/settings", tags=["settings"], dependencies=[Depends(require_auth)])


class SettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notion_token: str | None = Field(default=None, max_length=4096)
    notion_base_url: str | None = Field(default=None, max_length=2048)
    max_download_workers: int | None = Field(default=None, ge=1, le=16)
    max_upload_workers: int | None = Field(default=None, ge=1, le=16)
    enable_range_download: bool | None = None
    range_download_min_mb: int | None = Field(default=None, ge=1, le=102400)
    range_download_chunks: int | None = Field(default=None, ge=1, le=16)
    cache_auto_cleanup_enabled: bool | None = None
    cache_ttl_seconds: int | None = Field(default=None, ge=60, le=30 * 24 * 3600)
    cache_cleanup_interval_seconds: int | None = Field(default=None, ge=60, le=24 * 3600)
    theme_accent_color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    background: str | None = Field(default=None, max_length=4096)
    password: str | None = Field(default=None, min_length=1, max_length=1024)
    # 注意：channel 仅由环境变量 NFM_CHANNEL 决定，不通过 Web 修改

    @field_validator("notion_base_url")
    @classmethod
    def validate_notion_base_url(cls, v: str | None) -> str | None:
        if not v:
            return v
        try:
            assert_safe_remote_url(v)
        except UnsafeUrlError as e:
            raise ValueError(str(e)) from e
        return v.rstrip("/")


@router.get("")
async def get_settings():
    return config.public_dict


@router.put("")
async def put_settings(body: SettingsIn):
    patch = body.model_dump(exclude_none=True)
    for k, v in patch.items():
        if v is not None:
            if k not in config.as_dict():
                raise HTTPException(status_code=400, detail=f"未知配置项: {k}")
            config[k] = v
    config.save()
    return {"ok": True}
