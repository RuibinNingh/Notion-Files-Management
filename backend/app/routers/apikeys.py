"""API Key 管理路由：列表 / 创建 / 更新 / 删除。

仅 session 管理员或带 ``apikeys`` scope 的 key 可访问（见 ``deps.require_scope``）。
创建时只返回一次明文 key，之后接口永不返回明文。
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ..deps import require_scope
from ..apikeys import (
    ALL_SCOPES, BUSINESS_SCOPES, HIGH_RISK_SCOPES,
    create_key, list_keys, update_key, delete_key,
)

router = APIRouter(prefix="/api/apikeys", tags=["apikeys"],
                   dependencies=[Depends(require_scope("apikeys"))])


class KeyCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="未命名", min_length=1, max_length=120)
    scopes: list[str] = Field(min_length=1, max_length=20)
    expires_at: str | None = Field(default=None, max_length=40)  # ISO 8601 或留空
    rate_limit_rpm: int = Field(default=0, ge=0, le=100000)
    enabled: bool = True


class KeyUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=120)
    scopes: list[str] | None = Field(default=None, min_length=1, max_length=20)
    expires_at: str | None = Field(default=None, max_length=40)
    rate_limit_rpm: int | None = Field(default=None, ge=0, le=100000)
    enabled: bool | None = None


@router.get("")
async def list_():
    """列出所有 key（不含明文与 hash）。附带可用 scope 清单。"""
    return {
        "items": list_keys(),
        "scopes": {
            "business": list(BUSINESS_SCOPES),
            "high_risk": list(HIGH_RISK_SCOPES),
            "all": list(ALL_SCOPES),
        },
    }


@router.post("")
async def create(body: KeyCreateIn):
    try:
        rec, plaintext = create_key(
            name=body.name, scopes=body.scopes, expires_at=body.expires_at,
            rate_limit_rpm=body.rate_limit_rpm, enabled=body.enabled,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # 明文只此一次返回；前端务必提示用户保存
    return {"key": rec, "plaintext": plaintext}


@router.patch("/{key_id}")
async def update(key_id: str, body: KeyUpdateIn):
    # 用 model_fields_set 区分「字段未传」与「显式传 null」，
    # 这样 {"expires_at": null} 才能清空过期时间。
    fields = body.model_fields_set
    kwargs: dict = {}
    if "name" in fields:
        kwargs["name"] = body.name
    if "scopes" in fields:
        kwargs["scopes"] = body.scopes
    if "enabled" in fields:
        kwargs["enabled"] = body.enabled
    if "rate_limit_rpm" in fields:
        kwargs["rate_limit_rpm"] = body.rate_limit_rpm
    if "expires_at" in fields:
        kwargs["expires_at"] = body.expires_at  # 可能为 None（清空）
    try:
        rec = update_key(key_id, **kwargs)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if rec is None:
        raise HTTPException(status_code=404, detail="API Key 不存在")
    return {"key": rec}


@router.delete("/{key_id}")
async def delete(key_id: str):
    if not delete_key(key_id):
        raise HTTPException(status_code=404, detail="API Key 不存在")
    return {"ok": True}
