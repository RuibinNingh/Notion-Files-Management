"""鉴权路由：单一共享密码 + 签名 Session Cookie。"""
import secrets

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, Field

from ..config import config

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    password: str = Field(min_length=1, max_length=1024)


@router.post("/login")
async def login(req: Request, body: LoginIn):
    if not secrets.compare_digest(body.password, str(config["password"])):
        raise HTTPException(status_code=401, detail="密码错误")
    req.session["auth"] = True
    return {"ok": True}


@router.post("/logout")
async def logout(req: Request):
    req.session.clear()
    return {"ok": True}


@router.get("/check")
async def check(req: Request):
    return {"auth": bool(req.session.get("auth"))}
