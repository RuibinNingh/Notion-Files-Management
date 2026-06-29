<div align="center">

<br />

<img src="https://github.com/RuibinNingh/Notion-Files-Management/blob/main/icon.png?raw=true" alt="Notion Files Management" width="96" />

<br />

# Notion Files Management (Web)

**把 Notion 里的文件，真正变成你的文件。** —— Web 版重构。

批量下载 · 批量上传 · 页面工具箱 · 自动更新，全部跑在无头服务器上，浏览器访问即用。

[![Beta](https://img.shields.io/badge/渠道-Beta-f59e0b?style=flat-square)](#)
[![Release](https://img.shields.io/github/v/release/RuibinNingh/Notion-Files-Management?style=flat-square&color=22c55e&label=最新版本)](https://github.com/RuibinNingh/Notion-Files-Management/releases)
[![License](https://img.shields.io/badge/License-MIT-f59e0b?style=flat-square)](LICENSE)

> ⚠️ **当前为 Beta 预发布版本。** 原桌面版（WPF/C#）已停止维护，Web 版重构进行中，桌面版暂未上线。

</div>

> v2.0 是从原 WPF/C# 桌面版彻底重构而来：移除 C# 前端与 pythonnet 互操作，保留并复用原有 Python 业务逻辑，以 **FastAPI + Vue 3** 重建为可部署在无头服务器上的 Web 应用。

---

## 架构

```
notion-files-management/
├── backend/                 # FastAPI 后端
│   ├── app/
│   │   ├── main.py          # 应用入口：SessionMiddleware / 路由聚合 / 缓存清理线程 / 前端静态托管
│   │   ├── config.py        # 配置：环境变量 + config.json（对应原 AppConfig.cs）
│   │   ├── deps.py          # 双通道鉴权：session + Bearer API Key + scope + SSE token
│   │   ├── apikeys.py       # API Key 生成/hash(compare_digest)/校验/限流/CRUD（只存 hash）
│   │   ├── ssetokens.py     # 短期 SSE token（nfmsse_），10 分钟，绑定 task，进程内
│   │   ├── cors.py          # 动态 CORS 中间件（每请求读白名单，禁 * / null / 带 path）
│   │   ├── taskregistry.py  # 任务注册表 + SSE 推送（替代原 DispatcherTimer 轮询）
│   │   ├── notion_facade.py # Notion 业务 facade（替代原 main.py 的 Main 类，按任务隔离实例）
│   │   ├── staging.py       # 下载暂存 / zip 打包 / 缓存清理 / 日志列表
│   │   ├── app_version.py
│   │   └── routers/         # auth settings version notices scan download upload tools tasks system apikeys
│   ├── scripts/             # 复用原 Python 业务逻辑（notion/download/upload/migrate/...）+ scan.py
│   └── requirements.txt
├── frontend/                # Vue 3 + Vite + TS + Element Plus
│   └── src/{views,layouts,stores,composables,api,utils}/
├── docker/                  # Dockerfile + docker-compose.yml
└── deploy/                  # PyInstaller spec + systemd unit + run.py
```

**实时进度**：长任务（扫描/下载/上传/迁移）通过 **SSE** 推送，前端 `EventSource` 订阅。
**鉴权**：浏览器用单一共享密码（签名 Session Cookie，管理员全权限）；第三方用 `Authorization: Bearer nfm_...` API Key（按 scope 隔离）。
**部署**：Docker 单容器 或 PyInstaller 单文件 或 systemd + venv。

## 端口约定

以后统一使用这两个端口：

| 场景 | 前端 | 后端 / API | 说明 |
|------|------|------------|------|
| 本地开发 | `5173` | `18765` | Vite 开发服务器把 `/api` 代理到 `127.0.0.1:18765` |
| 单容器 / systemd / PyInstaller | — | `18765` | 后端直接托管 `frontend/dist` 静态文件 |

> 旧端口口径已废弃。

---

## 快速开始

### Docker（推荐）

```bash
# 构建并启动（首次会构建前端 + 安装后端依赖）
docker compose -f docker/docker-compose.yml up -d --build

# 查看随机生成的初始密码
docker logs nfm | grep "初始登录密码"
```

浏览器访问 `http://<服务器>:18765`，用日志里的密码登录，或在 `.env` 里设 `NFM_PASSWORD=你的密码` 固定密码。

### 本地开发

```bash
# 后端
python -m venv .venv && .venv/bin/pip install -r backend/requirements.txt
.venv/bin/uvicorn app.main:app --reload --app-dir backend --host 127.0.0.1 --port 18765   # http://127.0.0.1:18765

# 前端（另开终端）
cd frontend && npm install && npm run dev                    # http://127.0.0.1:5173（代理 /api → :18765）
```

首次启动若未设 `NFM_PASSWORD`，控制台会打印随机密码。

### 文档站

```bash
npm install
npm run docs:dev      # VitePress 本地预览
npm run docs:build    # 构建静态文档站
```

文档源码在 `docs/`；`AI/` 只作为开发交接和 Agent 协作资料。

---

## 配置

通过环境变量（部署）或设置页（运行时）配置，持久化到 `${NFM_DATA_DIR}/config.json`：

| 环境变量 | 默认 | 说明 |
|---------|------|------|
| `NFM_DATA_DIR` | `~/.notion-files-management` | 配置 / 暂存 / 日志 / 缓存根目录（Docker 内为 `/data`）|
| `NFM_PASSWORD` | （随机生成）| 访问密码，未设则首次启动随机生成并打印 |
| `NFM_NOTION_TOKEN` | （设置页填）| Notion Integration Token |
| `NFM_NOTION_BASE_URL` | `https://api.notion.com/v1` | Notion API 地址 |
| `NFM_MAX_DOWNLOAD_WORKERS` | `3` | 下载并发 |
| `NFM_MAX_UPLOAD_WORKERS` | `3` | 上传并发 |
| `NFM_FRONTEND_DIST` | `../frontend/dist` | 前端构建产物目录（PyInstaller / 自定义部署用）|
| `NFM_API_CORS_ALLOWED_ORIGINS` | （空）| 第三方浏览器跨域白名单，逗号分隔；默认不开放跨域 |
| `NFM_BOOTSTRAP_API_KEY` | （空）| 预置全权限 API Key（须 `nfm_` 前缀 + 负载 ≥ 32 字符，以 hash 落盘）|

Notion Token 也可登录后在 **设置** 页填写保存。

---

## 功能

| 页面 | 功能 |
|------|------|
| **主页** | 版本信息、官网/GitHub/赞助、版本更新检查 |
| **公告** | 卡片流式 + Markdown 渲染（markdown-it），已读管理 |
| **上传** | 多文件 / 文件夹上传（保留目录结构，子文件夹→子页面），SSE 进度 |
| **下载** | 流式扫描页面文件 + 实时大小探测 → 勾选 → 暂存下载 → 单文件 / ZIP 打包下载，链接过期自动刷新 |
| **工具箱** | 页面大小查询 / 页面大小自动更新 / 数据源迁移 / 批量去除后缀 |
| **API 密钥** | 为第三方调用签发 / 启停 / 删除 API Key（按 scope 隔离），管理跨域白名单 |
| **设置** | Token / 并发 / 主题色 / 密码 / 版本检查 / 清缓存 / 重启 |

---

## 第三方开放 API

除浏览器 session 外，业务接口支持 `Authorization: Bearer nfm_<明文>`。在 **API 密钥** 页创建 key（明文只显示一次，落盘只存 sha256 hash）。**长期 API Key 永远只走 Bearer 头，不放进 URL。**

```bash
# 发起扫描（key 需带 scan scope）
curl -X POST http://<host>:18765/api/scan \
  -H "Authorization: Bearer nfm_xxxxxxxx" -H "Content-Type: application/json" \
  -d '{"page_id":"<32位页面ID>","probe_workers":8}'
# => {"task_id":"..."}

# 查任务（需 tasks scope）
curl -H "Authorization: Bearer nfm_xxxxxxxx" http://<host>:18765/api/tasks
```

**SSE 进度**：`EventSource` 不能自定义头，长期 key 又不放进 URL，所以先换 10 分钟有效的短期 token：

```bash
TOK=$(curl -s -X POST -H "Authorization: Bearer nfm_xxxxxxxx" \
  http://<host>:18765/api/tasks/<task_id>/events-token | python3 -c "import sys,json;print(json.load(sys.stdin)['token'])")
curl -N "http://<host>:18765/api/tasks/<task_id>/events?events_token=$TOK"
```

| 状态 | 含义 |
|------|------|
| 401 | 未登录 / Key 无效·禁用·过期·伪造 / SSE token 无效或过期 |
| 403 | Key 缺少所需 scope |
| 429 | 触发该 Key 限流 |

**跨域**：默认不开放。在 API 密钥页配置白名单（动态生效）或设 `NFM_API_CORS_ALLOWED_ORIGINS`；仅允许 `http(s)` origin，禁 `*`/`null`/带路径。

---

## 独立部署（无 Docker）

```bash
# 1. 构建前端
cd frontend && npm ci && npm run build && cd ..

# 2. 方式 A：venv + systemd
python -m venv /opt/nfm/venv
/opt/nfm/venv/bin/pip install -r backend/requirements.txt
sudo cp -r backend /opt/nfm/backend
sudo cp -r frontend/dist /opt/nfm/frontend/dist
sudo install -d /var/lib/nfm
sudo cp deploy/systemd/nfm.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now nfm
# 反向代理（nginx）建议：把 / 转发到 127.0.0.1:18765 并配置 TLS

# 2. 方式 B：PyInstaller 单文件 / Windows exe
.venv/bin/pip install pyinstaller
.venv/bin/pyinstaller deploy/nfm.spec --noconfirm
# Windows 产物：dist/NOTION_FILES_MANAGEMENT_v<版本>-<渠道>.exe
# 双击后默认监听 127.0.0.1:18765 并打开浏览器；如需覆盖可设置 NFM_PORT
# Windows 默认数据目录：%LOCALAPPDATA%\Notion-Files-Management
# 日志目录：%LOCALAPPDATA%\Notion-Files-Management\logs
# Linux 服务器仍推荐 Docker 或 systemd + venv；此 spec 面向 Windows 迁移包。
```

---

## 系统要求

- 服务端：Linux x64（Docker / Python 3.11+ / Node 20+ 用于构建前端）
- 客户端：任意现代浏览器；Windows 迁移用户可使用 PyInstaller exe 本地启动 Web Console

---

## Star History

<a href="https://star-history.com/#RuibinNingh/Notion-Files-Management&Date">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=RuibinNingh/Notion-Files-Management&type=Date&theme=dark" />
    <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=RuibinNingh/Notion-Files-Management&type=Date" />
    <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=RuibinNingh/Notion-Files-Management&type=Date" />
  </picture>
</a>

---

## License

MIT © 2026 [Ruibin_Ningh](https://github.com/RuibinNingh) & Zyx_2012

---

<div align="center">
<sub>如果这个工具对你有用，欢迎 Star ⭐ 或提交 Issue / PR。</sub>
</div>
