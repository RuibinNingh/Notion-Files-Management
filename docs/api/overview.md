# 开放 API 总览

Notion Files Management 的后端是 FastAPI 服务。浏览器界面和第三方自动化程序调用的是同一套 API。

默认 API 地址：

```text
http://127.0.0.1:18765
```

Docker、systemd、Windows exe、本地开发默认都使用统一后端端口 `18765`。如果你在前面加了反向代理，把示例里的 host 换成自己的域名即可。

## 鉴权模型

NFM 有两条鉴权通道：

| 通道 | 使用者 | 凭据 | 权限模型 |
|------|--------|------|----------|
| Session Cookie | 浏览器管理界面 | `/api/auth/login` 登录密码 | 管理员，全权限 |
| API Key | 第三方程序 | `Authorization: Bearer nfm_...` | 按 scope 限权 |

第三方集成应使用 API Key。长期 API Key 不允许放在 URL 里，NFM 也不会接受 `?api_key=`。

## 长任务流程

扫描、下载、上传、迁移等操作都是长任务。多数接口会先返回 `task_id`，再通过任务接口读取状态或订阅 SSE 进度。

```text
POST /api/scan
  -> {"task_id":"..."}

GET /api/tasks/{task_id}
  -> 任务元数据和最新进度

GET /api/tasks/{task_id}/events
  -> text/event-stream 进度流
```

SSE 有一个特殊点：浏览器原生 `EventSource` 不能自定义 `Authorization` 请求头。第三方客户端应先用 Bearer key 换取短期 `events_token`，再用 `?events_token=` 连接事件流。

## Scope 总览

API Key 使用粗粒度 scope 控制权限。创建或更新 key 时传入未知 scope 会直接返回 `400`。

| Scope | 路由 | 用途 |
|-------|------|------|
| `scan` | `/api/scan/*` | 扫描 Notion 页面并列出可下载文件 |
| `download` | `/api/download/*` | 创建下载任务，获取单文件或 ZIP |
| `upload` | `/api/upload/*` | 暂存本地文件并上传到 Notion |
| `tools` | `/api/tools/*` | 页面大小更新、数据源迁移、去后缀、属性查询 |
| `tasks` | `/api/tasks/*` | 查看任务、取消、重试、换取 SSE token |
| `settings` | `/api/settings` | 读取或修改实例设置 |
| `logs` | `/api/logs*` | 读取或下载后端日志 |
| `cache` | `/api/cache/*` | 查看、下载、删除或清理缓存 |
| `system` | `/api/system/restart` | 重启后端进程 |
| `apikeys` | `/api/apikeys/*` | 管理 API Key |

前五个是常规业务 scope。`settings`、`logs`、`cache`、`system`、`apikeys` 属于高危 scope，只应授予可信自动化程序。

## 端点速览

### 公开与浏览器会话

| 方法 | 路径 | 鉴权 | 说明 |
|------|------|------|------|
| `POST` | `/api/auth/login` | 无 | 浏览器用共享密码登录 |
| `POST` | `/api/auth/logout` | session | 清除浏览器 session |
| `GET` | `/api/auth/check` | 无 | 返回 `{"auth": true/false}` |
| `GET` | `/api/version` | 无 | 当前版本与远程更新信息 |
| `GET` | `/api/version/channel` | 无 | 当前渠道 |
| `GET` | `/api/notices` | session 或 Bearer | 读取公告列表 |
| `GET` | `/api/notices/{nid}` | session 或 Bearer | 读取单条公告 |

### API Key 管理

需要浏览器管理员 session，或带 `apikeys` scope 的 API Key。

| 方法 | 路径 | 请求体 | 响应 |
|------|------|--------|------|
| `GET` | `/api/apikeys` | 无 | key 列表，不含明文和 hash，并返回可用 scope |
| `POST` | `/api/apikeys` | `name`、`scopes`、可选 `expires_at`、`rate_limit_rpm`、`enabled` | key 元数据和一次性 `plaintext` |
| `PATCH` | `/api/apikeys/{key_id}` | 部分字段 | 更新后的 key 元数据 |
| `DELETE` | `/api/apikeys/{key_id}` | 无 | `{"ok": true}` |

API Key 明文只在创建时返回一次。后端只保存 SHA-256 hash。

### 扫描

需要 `scan` scope。

| 方法 | 路径 | 请求体 | 响应 |
|------|------|--------|------|
| `POST` | `/api/scan` | `{"page_id":"...","probe_workers":8}` | `{"task_id":"..."}` |
| `GET` | `/api/scan/{task_id}/list` | 无 | `{"items":[...],"count":0}` |

`probe_workers` 取值范围是 `1` 到 `16`。

### 下载

需要 `download` scope。

| 方法 | 路径 | 请求体 | 响应 |
|------|------|--------|------|
| `POST` | `/api/download/start` | `{"items":[...],"page_id":"optional"}` | `{"task_id":"..."}` |
| `GET` | `/api/download/{task_id}/file/{idx}` | 无 | 文件响应 |
| `GET` | `/api/download/{task_id}/zip` | 无 | ZIP 文件响应 |

每个下载 item 需要安全的远程 `url`。推荐字段：`url`、`real_name`、`size_mb`、`block_id`。单个下载任务最多 `1000` 个 item。

### 上传

需要 `upload` scope。

| 方法 | 路径 | 请求体 | 响应 |
|------|------|--------|------|
| `POST` | `/api/upload/files` | `multipart/form-data`，包含 `files` 和可选 `rels` | 上传暂存 `session_id` |
| `POST` | `/api/upload/start` | `{"page_id":"...","session_id":"...","folder_mode":false}` | `{"task_id":"..."}` |

上传文件夹时，暂存阶段用 `rels` 传相对路径，启动阶段设置 `folder_mode: true`。

### 任务与 SSE

大多数任务接口需要 `tasks` scope。`GET /api/tasks/{task_id}/events` 例外，它接受三种凭据之一：session、Bearer + `tasks` scope、短期 `events_token`。

| 方法 | 路径 | 请求体 | 响应 |
|------|------|--------|------|
| `GET` | `/api/tasks` | 无 | 任务列表 |
| `GET` | `/api/tasks/{task_id}` | 无 | 任务详情 |
| `POST` | `/api/tasks/{task_id}/events-token` | 无 | `{"token":"nfmsse_...","expires_in":600}` |
| `GET` | `/api/tasks/{task_id}/events` | 无 | SSE stream |
| `POST` | `/api/tasks/{task_id}/cancel` | 无 | `{"ok": true}` |
| `POST` | `/api/tasks/{task_id}/retry` | 无 | `{"task_id":"..."}` |

SSE 事件：

| Event | Data |
|-------|------|
| `progress` | 最新进度对象 |
| `done` | 终态，例如 `{"status":"done"}` 或 `{"status":"error","error":"..."}` |

NFM 不使用自定义 `error` SSE 事件名，因为浏览器 `EventSource` 已经把 `error` 保留给连接错误。

### 工具

需要 `tools` scope。

| 方法 | 路径 | 用途 |
|------|------|------|
| `POST` | `/api/tools/properties` | 读取数据源属性 |
| `POST` | `/api/tools/page-size/scan` | 查找需要更新大小的页面 |
| `POST` | `/api/tools/page-size/start` | 启动页面大小更新任务 |
| `POST` | `/api/tools/migrate/props` | 读取源/目标数据源属性 |
| `POST` | `/api/tools/migrate/start` | 启动数据源迁移任务 |
| `POST` | `/api/tools/suffix/start` | 启动批量去后缀任务 |

### 设置、日志、缓存、系统

这些都是高危 scope。

| Scope | 方法 | 路径 | 用途 |
|-------|------|------|------|
| `settings` | `GET` | `/api/settings` | 读取公开设置 |
| `settings` | `PUT` | `/api/settings` | 更新设置 |
| `logs` | `GET` | `/api/logs` | 列出日志 |
| `logs` | `GET` | `/api/logs/{name}` | 读取日志尾部 |
| `logs` | `GET` | `/api/logs/{name}/download` | 下载单个日志 |
| `logs` | `POST` | `/api/logs/download` | 打包下载选中的日志 |
| `cache` | `GET` | `/api/cache/items` | 列出缓存项 |
| `cache` | `GET` | `/api/cache/items/{cache_id}/download` | 下载缓存项 |
| `cache` | `DELETE` | `/api/cache/items/{cache_id}` | 删除缓存项 |
| `cache` | `POST` | `/api/cache/cleanup` | 按策略清理过期缓存 |
| `cache` | `POST` | `/api/cache/clear` | 清空非运行中缓存 |
| `system` | `POST` | `/api/system/restart` | 重启进程 |

## 状态码

| 状态码 | 含义 |
|--------|------|
| `200` | 成功 |
| `400` | 请求体错误、scope 非法、不支持重试、上传 session 非法 |
| `401` | 未认证、API Key 无效/禁用/过期、SSE token 无效/过期 |
| `403` | API Key 有效但缺少所需 scope |
| `404` | task、key、文件、日志或缓存项不存在 |
| `409` | 缓存项仍被运行中的任务使用 |
| `422` | FastAPI / Pydantic 参数校验失败 |
| `429` | API Key 触发限流 |
