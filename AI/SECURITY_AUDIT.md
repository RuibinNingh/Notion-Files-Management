# 安全审计报告 (2026-06-29)

## 范围

本次审计覆盖 `backend/app/`、`backend/app/routers/`、`backend/scripts/`、`backend/app/staging.py`、`backend/app/taskregistry.py` 以及后端测试目录。重点检查路径穿越、SSRF、鉴权、Session、文件操作、输入验证、密码比较、CORS、敏感信息泄露。

## 结论

发现并修复 4 类可直接落地的小问题：

1. **SSRF**：`/api/download/start` 可传任意 `items[].url`，扫描和页面大小任务也会对 Notion external URL 做 HEAD/Range 探测。
2. **上传会话路径越界**：`/api/upload/start` 直接信任 `session_id`，已登录用户可传服务器任意目录，触发遍历并上传本地文件。
3. **密码比较**：登录密码使用普通字符串比较。
4. **输入验证不足**：多个路由的线程数、数组长度、字符串长度、配置值缺少 Pydantic 边界。

已新增测试覆盖主要路由和核心模块，验证命令已通过。

## 已修复

### SSRF 防护

新增 `backend/scripts/url_security.py`：

- 仅允许 `http` / `https`
- 拒绝 URL 内嵌用户名/密码
- 拒绝 `localhost`、`.local`、私网、环回、链路本地、保留地址
- DNS 解析后再次检查所有返回 IP
- `urllib` 重定向目标也会重新校验
- `requests` 文件大小探测禁用自动跟随重定向

接入点：

- `backend/app/routers/download.py`
- `backend/scripts/download.py`
- `backend/scripts/notion.py`
- `backend/scripts/page_size_update.py`

### 上传会话路径校验

`/api/upload/start` 现在只接受 `${NFM_DATA_DIR}/staging/upload-*` 的直属目录。相对 `session_id` 会按 staging 子项解析，绝对路径必须解析到 staging 直属 `upload-*` 目录，否则返回 400。

### 登录密码比较

`backend/app/routers/auth.py` 改为 `secrets.compare_digest()`，并限制密码输入长度。

### Pydantic 输入边界

已给以下路由补充 `extra="forbid"`、长度、数量、线程数范围等约束：

- `auth.py`
- `settings.py`
- `scan.py`
- `download.py`
- `upload.py`
- `tools.py`
- `system.py`

`notion_base_url` 也经过远程 URL 安全校验，避免配置成私网/本机地址。

### Session

`SessionMiddleware` 现在使用独立 cookie 名 `nfm_session`，`max_age=86400`，并支持通过 `NFM_SESSION_HTTPS_ONLY=1` 在 HTTPS 部署中启用 secure cookie。

## 审计项

| 攻击面 | 结果 |
|---|---|
| 路径穿越 | cache/log/download 文件读取已有直属子级或 basename 防护；已修复 upload start 任意目录问题 |
| SSRF | 已修复下载、扫描探测、页面大小探测、Notion base URL 配置入口 |
| 未授权访问 | 未发现 `/internal/*` 路由；业务路由均依赖 session，`/api/version*` 公开符合现有设计 |
| Session 安全 | 已加 cookie 名、过期时间、HTTPS secure env 开关；默认仍兼容本地 HTTP 开发 |
| 文件操作安全 | `zip_dir()` 使用相对路径写 zip，未发现 zip slip；新增测试验证归档名 |
| 输入验证 | 已补主要路由边界；复杂业务 payload 仍按 Notion API 透传 |
| 密码安全 | 已改 `secrets.compare_digest()` |
| CORS | 未配置 `CORSMiddleware`，未发现过宽 CORS |
| 敏感信息泄露 | `secret_key/password` 不在 settings 返回；`notion_token` 对已登录用户可见，符合单租户设置页需求 |

## 残余风险

1. **单租户模型**：已登录用户可以操作全局 Notion Token，这是项目既定架构，不是本次修复范围。
2. **DNS rebinding 竞态**：当前在请求前解析并检查 IP，已覆盖常见 SSRF，但未把连接固定到已验证 IP。高安全部署可进一步改为自定义 HTTP client 固定解析结果。
3. **`notion_token` 可见性**：已登录用户仍可读取完整 token。若未来支持多用户，需要改成按 session/token 隔离，并在设置接口做脱敏返回。
4. **CSRF**：Session cookie 认证的 POST 接口当前没有 CSRF token。`SameSite=Lax` 可缓解常见跨站 POST，但严格公网部署建议增加 CSRF token 或 Origin 校验。

## 测试覆盖

新增测试：

- `backend/tests/conftest.py`
- `backend/tests/test_auth_settings_version_notices.py`
- `backend/tests/test_scan_download_upload_routes.py`
- `backend/tests/test_tools_tasks_system_routes.py`
- `backend/tests/test_staging_taskregistry.py`
- `backend/tests/test_scripts_core.py`

覆盖内容：

- `backend/app/routers/` 下所有路由文件的主要路径
- `backend/scripts/` 下载、上传、Notion 提取、页面大小、迁移、批量改名核心逻辑
- `backend/app/staging.py`
- `backend/app/taskregistry.py`

## 验证

```bash
cd /home/ruibinningh/projects/Notion-Files-Management
.venv/bin/pytest backend/tests -q
# 35 passed

.venv/bin/python -m py_compile $(find backend/app backend/scripts -name '*.py')
# passed
```
