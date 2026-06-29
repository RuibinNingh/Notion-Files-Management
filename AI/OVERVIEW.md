# 项目概述

## 是什么

一个基于 **FastAPI + Vue 3** 的 Web 工具，帮用户：

1. **批量下载** Notion 页面里的所有文件（图片、视频、PDF、音频、文档……）
2. **批量上传** 本地文件 / 文件夹到 Notion
3. **页面大小自动更新**：扫描数据源中所有页面的文件大小，写入指定数字属性
4. **数据源迁移**：把一个数据库的属性按映射复制到另一个
5. **批量去后缀**：去掉一批页面标题里相同的尾巴（比如 `(1)`）
6. **页面大小查询**：单页查询所有文件及总大小
7. **全局任务看板**：统一查看、取消、重试扫描/上传/下载等长任务
8. **云端缓存管理**：查看、下载、删除上传缓存/下载产物/临时 zip，并配置自动清理

## 完整技术栈

| 层 | 技术 |
|----|------|
| **前端** | Vue 3 (script setup) + Vite 5 + TypeScript 5 + Element Plus 2.7 (暗色) + Pinia 2 + Vue Router 4 + Axios + markdown-it |
| **后端** | Python 3.11 + FastAPI 0.115 + Uvicorn + sse-starlette + itsdangerous (SessionMiddleware) + requests + pydantic 2 |
| **进程间** | （之前是 pythonnet，已废弃）后端现在是独立 Python 进程，前端通过 HTTP/SSE 通信 |
| **Notion API** | v2025-09-03（含 Data Sources API） |
| **部署** | Docker 多阶段 / PyInstaller 单文件 / venv+systemd |
| **文档站** | VitePress 1.6（根目录 `npm run docs:*`，内容在 `docs/`） |
| **持久化** | `${NFM_DATA_DIR}/config.json` + 同目录下 `staging/` `logs/` `notices_cache/` |

## 顶层目录

```
.
├── backend/              # FastAPI 后端
│   ├── app/             # 应用代码（routers/、facade、config、auth、apikeys）
│   ├── scripts/         # 从老 C# 项目的 Scripts/ 平移过来，几乎未改
│   ├── tests/           # pytest 冒烟测试
│   └── requirements.txt
├── frontend/             # Vue 3 前端
│   ├── src/views/        # Dashboard / Tasks / Cache / Upload / Download / Tools / ApiKeys / Settings / Notice / Login
│   ├── src/layouts/      # MainLayout.vue（侧栏 + 顶栏）
│   ├── src/stores/       # Pinia：auth、config、tasks
│   ├── src/composables/  # useTask（SSE 订阅）
│   ├── src/api/          # client.ts（axios + 401 拦截）
│   └── src/utils/        # pageId（NotionPageId TS 移植）、format
├── docker/               # Dockerfile + docker-compose.yml
├── deploy/               # PyInstaller spec + Windows entry + systemd unit + run.py
├── docs/                 # VitePress 用户文档 / API 文档 / 部署文档 / 历史版本说明
│   └── .vitepress/       # 文档站配置、主题覆盖
├── .github/workflows/    # GitHub Actions（docs.yml 发布文档；windows-exe.yml 打包 Windows exe）
├── AI/                   # 交接文档（你正在看）
├── package.json          # VitePress 文档站脚本（不承载前端应用）
├── icon.ico / icon.png   # 仓库展示用图标（应用不再用）
├── LICENSE
└── README.md
```

## 后端 `app/` 速览

```
backend/app/
├── main.py              # 入口：SessionMiddleware、路由聚合、缓存清理线程、SPA 静态托管
├── config.py            # Config 类：env + config.json 合并
├── deps.py              # 双通道鉴权依赖：session + Bearer API Key + scope + SSE events_token
├── apikeys.py           # API Key 生成/hash/校验/限流/CRUD(只存 hash,compare_digest)
├── ssetokens.py         # 短期 SSE token(nfmsse_),10分钟,绑定 task_id,进程内
├── cors.py              # 动态 CORS 中间件(每请求读白名单,禁 */null/path)
├── taskregistry.py      # 任务注册表 + SSE 推送（核心）
├── staging.py           # 暂存目录 / zip 打包 / 缓存列表 / 缓存清理 / 日志列表
├── notion_facade.py     # Notion 业务 facade（替换原 C# 的 Main 类）
├── app_version.py       # APP_VERSION 字符串
└── routers/             # FastAPI 路由
    ├── auth.py          # POST /api/auth/{login,logout,check}
    ├── settings.py      # GET/PUT /api/settings
    ├── version.py       # GET /api/version（公开，代理远程 version.json）
    ├── notices.py       # GET /api/notices, /api/notices/{id}
    ├── scan.py          # POST /api/scan, GET /api/scan/{tid}/list
    ├── download.py      # POST /api/download/start, GET /api/download/{tid}/{file/idx,zip}
    ├── upload.py        # POST /api/upload/files, /api/upload/start
    ├── tools.py         # 4 个 Notion 工具（页面大小、迁移、去后缀、属性查询）
    ├── tasks.py         # 任务列表 / 详情 / SSE(events-token) / 取消 / 重试
    ├── apikeys.py       # API Key 管理：GET/POST /api/apikeys、PATCH/DELETE /api/apikeys/{id}
    └── system.py        # /api/logs, /api/cache/*, /api/system/restart
```

## 关键概念

| 概念 | 含义 |
|------|------|
| **Task** | 一个长任务（扫描/下载/上传/迁移等），有 `task_id`、状态、进度 |
| **TaskHandle** | `taskregistry.py` 里的 dataclass，持有 task 状态 + 进度 + SSE 订阅者 |
| **TaskRegistry** | 全局 `registry` 单例，管理所有 task + 启动轮询协程 |
| **Task retry** | `TaskHandle.retry_fn` 保存重试闭包，`POST /api/tasks/{tid}/retry` 创建新任务 |
| **Cache item** | `${NFM_DATA_DIR}/staging` 直属文件/目录，按 `upload-` / `download-` / `generated-` 前缀分类；`id` 是存储名，`name` 是元数据里的可读展示名 |
| **SSE** | Server-Sent Events，浏览器用 `EventSource` 订阅 `/api/tasks/{id}/events` |
| **Poll 协程** | 注册表为每个 task 起的 `asyncio` 协程，每 0.4s 调一次后端 poll 函数，diff 后 push 给订阅者 |
| **Facade** | `notion_facade.py` 的 `NotionFacade` 类，把后端 Notion / Download / Upload 对象封成「按任务隔离」的实例 |
| **API Key** | 第三方调用凭据 `nfm_...`，只存 sha256 hash；带 scope/过期/限流/启停，明文只创建时返回一次 |
| **Scope** | API Key 的权限分组：业务 `scan/download/upload/tools/tasks`，高危 `settings/system/logs/cache/apikeys`。session 登录不受限 |
| **Task 终态事件** | 后端统一发 `event: "done"`，data 里 `status` 区分 `done/error/cancelled`（避免和 EventSource 原生 `error` 冲突） |

## 不在范围内

- ❌ 不是 Notion 官方工具，仅是第三方辅助
- ❌ 不支持实时协作 / WebSocket 双向通信（仅 SSE 单向推送进度）
- ❌ Notion OAuth（用 Integration Token，不做用户授权流程）
- ❌ 多租户 / 用户系统（单租户：服务端一个 Notion Token + 一个共享密码）
