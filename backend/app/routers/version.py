"""版本检查路由：按渠道（Status/Beta）代理到不同的服务端 endpoint。
公开端点，公开不同渠道的更新信息（Beta 不与 Status 混，避免被强升）。"""
import anyio
import requests
from fastapi import APIRouter

from ..config import config
from ..app_version import VALID_CHANNELS, version_for_channel

router = APIRouter(prefix="/api/version", tags=["version"])

# 按渠道路由到不同的更新端点
_ENDPOINTS = {
    "Status": (
        "https://nfm.ruibin-ningh.top/version.json",
        "http://nfm.ruibin-ningh.top/version.json",
    ),
    "Beta": (
        "https://beta.nfm.ruibin-ningh.top/version.json",
        "http://beta.nfm.ruibin-ningh.top/version.json",
    ),
}


def _fetch(channel: str):
    endpoints = _ENDPOINTS.get(channel) or _ENDPOINTS["Status"]
    for url in endpoints:
        try:
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            return r.json()
        except Exception:
            continue
    return None


@router.get("")
async def version():
    channel = config.channel
    local_version = version_for_channel(channel)
    data = await anyio.to_thread.run_sync(_fetch, channel)
    if not data:
        return {"local": local_version, "channel": channel, "remote": None}
    data["local"] = local_version
    data["channel"] = channel
    return data


@router.get("/channel")
async def channel():
    """返回当前实例的渠道（Status / Beta）。"""
    return {"channel": config.channel, "valid": list(VALID_CHANNELS)}
