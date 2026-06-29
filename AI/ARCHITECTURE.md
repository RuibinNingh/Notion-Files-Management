# 架构原理

> 读这一份前先看 `OVERVIEW.md`。

## 整体数据流

```
┌──────────┐  HTTP/SSE  ┌──────────┐  Python  ┌──────────┐  HTTPS  ┌─────────┐
│ Browser  │ ──────────▶│ FastAPI  │ ────────▶│ Notion   │ ──────▶│ Notion  │
│ (Vue 3)  │ ◀────────── │ (18765)  │          │ Facade   │         │ API     │
└──────────┘  EventSource└──────────┘          └──────────┘         └─────────┘
     │                  │                       │
     │ cookies          │ 派发到后台线程池       │
     │ (session)        │                       ▼
     │                  │             ┌──────────────────┐
     │                  │             │ Scripts/*.py     │
     │                  │             │  (Notion/Download│
     │                  │             │   /Upload/Migrate│
     │                  │             │   /...)          │
     │                  │             └──────────────────┘
     │                  │                       │
     │                  │  写 staging/           │
     │                  │  写 logs/              │
     │                  │  写 config.json        │
     │                  ▼                       │
     │              ${NFM_DATA_DIR}              │
```

## 后端：一次完整「下载」请求的旅程

以「下载一个 Notion 页面」为例：

### 1. 浏览器侧（用户点「扫描」）

```vue
// Download.vue
const r = await api.post('/api/scan', { page_id: pageId.value, probe_workers: 8 })
scanTaskId.value = r.data.task_id
scanTask.start(r.data.task_id, callback)  // 订阅 SSE
```

`scanTask` 是 `useTask()` 返回的响应式对象，`.start()` 内部 `new EventSource('/api/tasks/{id}/events', { withCredentials: true })`。

### 2. 后端路由（FastAPI）

```python
# routers/scan.py
@router.post("")
async def scan(body: ScanIn):
    h = facade.start_scan(body.page_id, body.probe_workers)
    return {"task_id": h.task_id}
```

`facade.start_scan()` 同步：
- 创建一个新的 `ScanSession`（`scripts/scan.py`）
- 在该 session 里启动两个后台线程：worker（递归查 blocks + 入队 URL）和 probe consumer（HEAD/Range GET 探测大小）
- 调用 `registry.create("scan", ...)` 注册任务 → 立即返回 task_id

### 3. TaskRegistry 启动轮询协程

```python
# taskregistry.py
def create(self, kind, *, poll_fn, ...):
    h = TaskHandle(...)
    self._tasks[tid] = h
    if poll_fn:
        self._loops[tid] = asyncio.create_task(self._poll_loop(h))
    return h

async def _poll_loop(self, h):
    while not h.terminal:
        data = await anyio.to_thread.run_sync(h.poll_fn)  # 调 facade 的 poll
        async with h._lock:
            h.progress = data
            if data.get("done"):
                h.terminal = True
                await self._fanout(h, {"event": "done", "data": ...})
                break
            await self._fanout(h, {"event": "progress", "data": data})
        await asyncio.sleep(0.4)
```

`facade.start_scan` 注册时传入的 `poll_fn`：
```python
def poll():
    st = session.get_status()
    st["done"] = bool(st.get("done") and st.get("probing_done"))
    st["items_count"] = len(session.read_list())
    return st
```

这个 `poll_fn` 是同步函数，`anyio.to_thread.run_sync` 把它扔到线程池，不阻塞事件循环。

### 4. 浏览器接收 SSE 事件

```js
es.addEventListener('progress', (e) => {
  state.progress = JSON.parse(e.data)  // 包含 discovered/files_probed/total_urls
})
es.addEventListener('done', (e) => { ... })
```

`fanout` 把消息 push 到每个订阅者的 `asyncio.Queue`；SSE 端点（`routers/tasks.py`）的 async generator 从队列取出来 yield 给 `EventSourceResponse`。

### 5. 浏览器拉取文件列表

扫描进行中，前端每 800ms 调一次：
```js
const r = await api.get(`/api/scan/${tid}/list`)
scanItems.value = r.data.items  // [{url, real_name, size_mb, block_type, ...}, ...]
```

后端 `routers/scan.py` 的 `scan_list` 调用 `facade.read_scan_list(tid)`，从 `ScanSession` 读 `download_list`（后台 worker 实时填充的）。

### 6. 用户勾选文件 → 启动下载

```js
const r = await api.post('/api/download/start', { items: selected.value })
dlTaskId.value = r.data.task_id
dlTask.start(r.data.task_id)  // 第二个 SSE 订阅，看下载进度
```

后端 `facade.start_download(items, save_dir)`：
- 创建新 `Download(max_workers=...)` 实例（**每任务独立**）
- 读取 `enable_range_download` / `range_download_min_mb` / `range_download_chunks` 注入实验性分片配置
- 为每个 item 创建 `_make_url_refresh_callback(block_id)` 闭包（链接过期时自动 `notion.refresh_file_url` 拿新链接）
- 调用 `dl.download(url, save_path, size, refresh_cb, max_url_refresh=2)`
- 返回 handle，含 `poll_fn` 读取 `dl.get_status(url)` per item

实验性分片下载只在以下条件都满足时启用:

- `enable_range_download=true`
- 文件大小大于等于 `range_download_min_mb`
- `GET Range: bytes=0-0` 返回 `Content-Range`,可得到总大小

分片下载会生成 `*.partNNN` 临时文件和 `*.merge` 合并文件,完成后 `os.replace()` 到目标文件。探测失败或低于阈值会回退单连接;分片执行失败会记录错误并清理临时文件。日志前缀为 `[DownloadRange]`。

### 7. 下载完成 → 取回文件/zip

```js
window.open(`/api/download/${tid}/file/${idx}`)  // 单文件
window.open(`/api/download/${tid}/zip`)          // zip 打包
```

后端 `routers/download.py` 从 `h.meta["dir"]` 找到暂存目录，发送文件 / 调 `staging.zip_dir()` 打包流式返回。

---

## 全局任务看板

`TaskRegistry` 现在不仅保存进度,也保存任务管理元数据:

```python
# backend/app/taskregistry.py
TaskHandle(
    task_id=tid,
    kind=kind,
    title=title,
    source=source,
    input=input or {},
    retry_fn=retry_fn,
    retryable=retryable,
    artifact=artifact or {},
    cache_refs=cache_refs or [],
)
```

核心接口:

```
GET  /api/tasks                  # 全局任务列表
GET  /api/tasks/{tid}            # 单任务详情
GET  /api/tasks/{tid}/events     # SSE 进度
POST /api/tasks/{tid}/cancel     # 取消
POST /api/tasks/{tid}/retry      # 创建一个新任务
```

前端 `frontend/src/stores/tasks.ts` 是全局任务状态源:

```
Tasks.vue / Dashboard.vue / Upload.vue / Download.vue
        │
        ▼
useTasksStore()
        │ load / track / cancel / retry
        ▼
/api/tasks + EventSource('/api/tasks/{tid}/events')
```

上传/下载页现在主要负责创建任务;任务创建后调用 `tasks.load()` + `tasks.track(task_id)`,再弹窗询问是否前往任务看板。任务看板统一负责取消和重试。

---

## 云端缓存管理

缓存仍落在 `${NFM_DATA_DIR}/staging`,但新建目录带类型前缀:

```
staging/
├── upload-<id>/       # 浏览器上传到服务器的缓存
├── download-<id>/     # Notion 下载到本地的产物
│   └── .nfm-cache.json # 可读展示名/类型等元数据
└── generated-*.zip    # 下载目录/日志打包生成的 zip
    └── generated-*.zip.meta.json # 文件型缓存 sidecar 元数据
```

缓存 API 的 `id` 仍是底层存储名,用于下载/删除和任务引用;`name` 是给 UI 展示的可读名称,来自 `.nfm-cache.json` 或 `*.meta.json` 的 `display_name`。前端缓存页同时展示可读名称和较淡的 `storage_name`,方便和日志/文件系统排查对照。

缓存 API:

```
GET    /api/cache/items
GET    /api/cache/items/{cache_id}/download
DELETE /api/cache/items/{cache_id}
POST   /api/cache/cleanup
POST   /api/cache/clear
```

`staging.cleanup_old_staging(max_age_seconds, protected_paths)` 会跳过 `registry.active_cache_refs()` 返回的运行中任务缓存。设置项:

- `cache_auto_cleanup_enabled`
- `cache_ttl_seconds`
- `cache_cleanup_interval_seconds`
- `enable_range_download`
- `range_download_min_mb`
- `range_download_chunks`

`main.py` 启动后执行一次清理;非 pytest 环境下启动 daemon `CacheCleanup` 线程定期清理。

---

## 关键设计决策

### 为什么「每任务一个 Download 实例」？

原 C# 版本 `Main` 类共用一个 `Download.downloader`，全局 `download_list`。如果两个用户同时下载不同页面，状态会互相污染。

新设计：facade 每次 `start_download` 都 `new Download(max_workers=...)`，**task_id 与 Download 实例一一对应**。进程结束调 `dl.shutdown(wait=False)` 释放线程。

> ⚠️ Download 实例不是线程安全的（`status_map` 没有 lock），所以**绝对不能跨任务共享**。

### 为什么 SSE 终态事件统一是 `done` 而不是 `error`？

EventSource 原生有一个 `error` 事件（连接断开时触发）。如果后端也发名为 `error` 的自定义 SSE 事件，浏览器无法区分「后端报告错误」和「连接断了」。

解决：后端**所有终态**（完成 / 失败 / 取消）都发 `event: "done"`，用 `data.status` 区分：
- `{event: "done", data: {status: "done"}}`
- `{event: "done", data: {status: "error", error: "..."}}`
- `{event: "done", data: {status: "cancelled"}}`

前端 `useTask.ts` 只有一个 `done` 监听器，根据 `data.status` 分支处理。

### 为什么 `notion_facade.py` 里的 `start_*` 方法都是同步的？

```python
@router.post("/api/download/start")
async def start(body: StartIn):  # async 路由
    h = facade.start_download(body.items, save_dir)  # 同步调用
    return {"task_id": h.task_id}
```

`start_download` 内部只是 `new Download()` + 调 `dl.download()` 入队（`executor.submit`），**不会阻塞**。直接同步调用即可，省去 `anyio.to_thread` 的开销。

如果哪天某个 `start_*` 真的需要阻塞（比如 `start_scan` 改成立即返回第一个文件），**必须**用 `anyio.to_thread.run_sync` 包装。

### 为什么 scripts/ 里的模块用 `from logger import PythonLogger` 这种绝对导入？

`backend/scripts/` 在 sys.path 上（main.py 第一行 `sys.path.insert(0, str(SCRIPTS_DIR))`）。这样原 Scripts/*.py 几乎不用改。

**不要**改成 `from .logger` 相对导入，那会破坏平移的"零改动"承诺。

### 为什么 API Key 只存 hash，且 session 优先于 Bearer？

- **只存 hash**：`config.json` 的 `api_keys[]` 只存 `sha256(明文)`，明文不可逆；比较用 `secrets.compare_digest` 做常量时间比较。创建时返回一次，前端弹窗强提示保存。丢失只能删除重建——这是有意的安全取舍，不要为「方便查看」把明文落盘。
- **session 优先**：`resolve_auth` 先判 `request.session['auth']`。浏览器管理员永远全权限、不受 scope 约束；API Key 只管第三方。测试 Bearer 鉴权时必须用未登录的 client（`GOTCHAS.md` 第 22 条）。
- **长期 key 只走 Bearer**：任何接口都不接受 `?api_key=`（避免明文进日志/Referer）。SSE 用短期 `nfmsse_` token 兜底（`GOTCHAS.md` 第 24 条）。
- **scope 粗粒度且严格**：按功能分组，未知 scope 直接 400（不静默过滤）。session 免校验，key 必须显式持有。高危 scope(`settings/system/logs/cache/apikeys`)默认不勾选。
- **限流进程内**：滑动窗口在 `apikeys._rate_buckets` 内存里，多进程部署下各自计数（已知限制，单进程/单租户够用）。SSE token 同样进程内，重启失效。

---

## 前端状态管理

### Pinia stores

- **auth**：`isLoggedIn`、`checked`、`check()`、`login()`、`logout()`
- **config**：`config`（从后端拉的配置对象）、`load()`、`save()`
- **tasks**：全局任务列表、运行中 SSE 订阅、取消、重试、最近任务

### 跨页共享的"任务状态"

当前有专门的 `tasks` store。页面级 `useTask()` 仍保留给 Download 页扫描/局部进度兼容,但全局任务展示和管理都走 `useTasksStore()`。

创建云端上传/下载任务后:

```ts
await tasks.load()
tasks.track(taskId)
// 弹窗确认后再 router.push('/tasks')
```

任务看板和主页小面板共享同一份 Pinia 状态。切页面不会丢失任务列表;运行中任务会通过 store 的 EventSource 继续更新。

扫描任务的文件结果不放进全局 SSE 进度里。`Tasks.vue` 展开扫描任务详情时,按需调用 `GET /api/scan/{task_id}/list` 读取 `ScanSession.download_list`,展示扫描到的文件名、大小和来源标识。这样任务列表保持轻量,也避免大量文件时每次进度推送都传完整列表。

### `reactive(state)` vs `ref(...)` 陷阱

`useTask` 早期返回 refs 嵌套在对象里，**模板里 `task.progress.files_probed` 报错**（ref 不会自动解包嵌套属性）。改成返回 `reactive({ progress, status, error, done })` 后才能在模板深层访问。

⚠️ 在 vue 模板里访问 `state` 中的属性时，**不要在 setup 里写 `const progress = task.progress` 然后在模板用 `progress.x`** —— 这样会把 ref 暴露成普通值，丢失响应性。直接写 `task.state.progress.x`。

---

## 鉴权流（双通道）

```
请求进来
   │
   │ deps.resolve_auth(request, credentials)
   ▼
┌─────────────────────────────────────────────────┐
│ 1. session cookie: request.session['auth'] ?    │
│    是 → 管理员，全权限，跳过 scope 校验          │
└─────────────────────────────────────────────────┘
   │ 否
   ▼
┌─────────────────────────────────────────────────┐
│ 2. Authorization: Bearer nfm_...                │
│    （长期 API Key 永远只走 Bearer，不接受 query）│
│    apikeys.verify_key() 校验 hash/启停/过期      │
│    失败/禁用/过期/伪造 → 401                      │
│    check_rate_limit() 超限 → 429                  │
│    record_usage() 节流写 last_used(60s 一次)     │
└─────────────────────────────────────────────────┘
   │
   ▼
require_scope("scan") 等：needed & granted 为空 → 403
   │
   ▼
路由业务逻辑
```

**两条通道**：

- **浏览器**：`POST /api/auth/login` 比对 `config['password']`，通过则 `req.session['auth']=True`，`SessionMiddleware`(itsdangerous) 签名 cookie。浏览器管理员始终全权限，**不受 scope 约束**。
- **第三方**：`Authorization: Bearer nfm_<明文>`。明文不落盘，`config.json` 的 `api_keys[]` 只存 `sha256(明文)`，比较用 `secrets.compare_digest`。**长期 API Key 永远只走 Bearer 头**，任何接口都不接受 `?api_key=` query 参数。

**SSE 的特殊处理**：浏览器 `EventSource` 不能自定义请求头，又不能把长期 key 放 URL。折中方案——短期 `nfmsse_` token：

```
第三方/浏览器  POST /api/tasks/{tid}/events-token   (需 session 或 Bearer+tasks scope)
              └─▶ {"token":"nfmsse_...","expires_in":600}   (绑定 tid，10 分钟，进程内)
              GET /api/tasks/{tid}/events?events_token=nfmsse_...
```

`GET /{tid}/events` 的鉴权走 `deps.require_events_access`（session / Bearer+tasks scope / events_token 三选一），**不**挂路由级 `require_scope`——否则 query token 会被 401 拦掉。`?events_token=` 是唯一允许出现在 URL 的凭据，且短期、单任务绑定。

**scope → 路由对照**：

| scope | 路由 | 风险 |
|-------|------|------|
| `scan` | `/api/scan/*` | 业务 |
| `download` | `/api/download/*` | 业务 |
| `upload` | `/api/upload/*` | 业务 |
| `tools` | `/api/tools/*` | 业务 |
| `tasks` | `/api/tasks/*`（含 SSE） | 业务 |
| `settings` | `/api/settings` | 高危 |
| `logs` | `/api/logs*` | 高危 |
| `cache` | `/api/cache/*` | 高危 |
| `system` | `/api/system/restart` | 高危 |
| `apikeys` | `/api/apikeys/*` | 高危 |

`notices`/`version` 不绑 scope：`version` 公开，`notices` 用 `require_auth`（任意已登录身份即可读）。

**API Key 生命周期**：创建/更新拒绝空 scope、未知 scope（直接 400，不静默过滤）、非法过期时间；过期时间统一存 UTC ISO。`PATCH /api/apikeys/{id}` 用 `body.model_fields_set` 区分「字段未传」与「显式 null」，所以 `{"expires_at": null}` 能清空过期时间（`update_key` 用 `_UNSET` 哨兵）。`NFM_BOOTSTRAP_API_KEY` 预置 key 严格要求 `nfm_` 前缀 + 负载 ≥ 32 字符，弱值忽略并 warning，不自动补前缀（见 `GOTCHAS.md` 第 26 条）。

**CORS（动态）**：默认不开放跨域。`app/cors.py` 的 `DynamicCORSMiddleware` 常驻，**每次请求**实时读 `config["api_cors_allowed_origins"]`，改设置无需重启。仅放行 `http(s)://` origin，拒绝 `*`、`null`、带 path/query 的值（`is_valid_origin` 校验）；OPTIONS preflight 只对白名单 origin 返回 CORS 头。本中间件始终 `allow_credentials=true`，所以 `*` 永不放行。白名单在「API 密钥」页管理（经 `PUT /api/settings` 的 `api_cors_allowed_origins` 字段）。

**SessionMiddleware 关键配置**（`main.py`）：
```python
app.add_middleware(
    SessionMiddleware,
    secret_key=config["secret_key"],   # 从 config.json 加载，无则首次启动随机生成
    session_cookie="nfm_session",
    same_site="lax",                   # 允许跨页跳转带 cookie
    https_only=_env_bool("NFM_SESSION_HTTPS_ONLY", False),
    max_age=24 * 60 * 60,
)
```

---

## 与 C# 旧版的对照

| C# 旧版 | Web 新版 |
|---------|----------|
| `Main` 单例持有全局 `Download` + `download_list` | facade 每次 new `Download`，按 task 隔离 |
| UI 线程 + DispatcherTimer 每秒轮询 `get_download_statuses` | 浏览器 EventSource 订阅 SSE，零轮询 |
| C# 调用 `Main.start_scan` 同步返回 `probe_id` | 路由立即返回 `task_id`，后台线程跑扫描 |
| `Main` 注入 dotenv stub | 后端原生用 `python-dotenv` |
| C# WPF UI 渲染（El-Icon/XAML） | Vue 3 + Element Plus |
| 单机单用户 | 单服务多用户（共享同一 Notion Token，共享密码） |
| 桌面 exe，绑 Windows | Docker / PyInstaller / venv+systemd |

### Windows exe 入口为何独立？

Docker / systemd 走服务端入口：`uvicorn app.main:app` 或 `deploy/run.py`，只负责启动 API 服务。

Windows 迁移用户需要双击即用的本地体验，所以 PyInstaller spec 指向 `deploy/windows_entry.py`：

- exe 产物名为 `NOTION_FILES_MANAGEMENT_v<版本>-<渠道>.exe`
- 默认数据目录为 `%LOCALAPPDATA%\Notion-Files-Management`
- 日志目录为 `%LOCALAPPDATA%\Notion-Files-Management\logs`
- 配置文件为 `%LOCALAPPDATA%\Notion-Files-Management\config.json`
- 缓存目录为 `%LOCALAPPDATA%\Notion-Files-Management\staging`
- 默认监听 `127.0.0.1:18765`，与 Docker/systemd/dev 统一；如需覆盖端口可设置 `NFM_PORT`
- 启动后自动打开默认浏览器

这个入口只在打包 exe 时触发，不影响 Docker 容器。

Windows exe 自动打包走 `.github/workflows/windows-exe.yml`：

```text
push tag v* / workflow_dispatch
        |
        v
windows-latest
  npm ci && npm run build          # 生成 frontend/dist
  pip install -r backend/requirements.txt + pyinstaller
  pyinstaller deploy/nfm.spec      # 使用 deploy/windows_entry.py
        |
        v
dist/NOTION_FILES_MANAGEMENT_v2.0.0-Beta.exe
        |
        +--> workflow artifact
        +--> tag 触发时上传 GitHub Release asset
```

原因：PyInstaller 不支持在 Linux 上直接交叉编译真正可运行的 Windows `.exe`，所以 Windows 迁移包必须在 Windows runner 或本机 Windows 上打。

---

## 跨任务状态（已知限制）

- **后端 `Main.download_list` 改为 facade 私有**：facade 内部的状态隔离。
- **上传/下载/扫描可同时进行**：每个 task 独立 `Download`/`Upload` 实例。
- **共享 Notion API 限流**：每个任务类内部有限流（`Upload` 有 TokenBucket，`migrate`/`batch_rename` 有 0.4s 间隔），但**没有跨任务全局限流**。如果同时跑两个大任务，可能触发 Notion 429。
  - 计划中的「全局速率限制器」未实现（`ratelimit.py` 不存在），见 `GOTCHAS.md`。
