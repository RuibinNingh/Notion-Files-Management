"""鉴权依赖：单一共享密码 + 签名 Session Cookie。"""
from fastapi import HTTPException, Request


def require_auth(request: Request) -> bool:
    if not request.session.get("auth"):
        raise HTTPException(status_code=401, detail="未登录")
    return True
