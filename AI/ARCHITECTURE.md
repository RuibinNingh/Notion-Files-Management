# 架构原理

> 读这一份前先看 `OVERVIEW.md`。

## 整体数据流

```
┌──────────┐  HTTP/SSE  ┌──────────┐  Python  ┌──────────┐  HTTPS  ┌─────────┐
│ Browser  │ ──────────▶│ FastAPI  │ ────────▶│ Notion   │ ──────▶│ Notion  │
│ (Vue 3)  │ ◀────────── │ (8765)   │          │ Facade   │         │ API     │
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

## 鉴权流

```
用户打开 http://localhost:5173/download
   │
   │ 路由守卫 (router.ts beforeEach):
   │   if (to.meta.public) return true   ← /login
   │   if (!auth.isLoggedIn) await auth.check()  ← /api/auth/check
   │   if (!auth.isLoggedIn) return { name: 'login' }  ← 重定向
   │
   ▼
登录页：POST /api/auth/login {password}
   │
   │ 后端：与 config['password'] 做 secrets.compare_digest 比较
   │ 通过：req.session['auth'] = True
   │ SessionMiddleware 用 itsdangerous 签名 cookie
   │
   ▼
后续请求：浏览器自动带 cookie → deps.require_auth 检查 session['auth']
```

**SessionMiddleware 关键配置**（`main.py`）：
```python
app.add_middleware(
    SessionMiddleware,
    secret_key=config["secret_key"],   # 从 config.json 加载，无则首次启动随机生成
    same_site="lax",                   # 允许跨页跳转带 cookie
    https_only=False,                  # 本地开发用 http，生产建议改 True + 反代
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

---

## 跨任务状态（已知限制）

- **后端 `Main.download_list` 改为 facade 私有**：facade 内部的状态隔离。
- **上传/下载/扫描可同时进行**：每个 task 独立 `Download`/`Upload` 实例。
- **共享 Notion API 限流**：每个任务类内部有限流（`Upload` 有 TokenBucket，`migrate`/`batch_rename` 有 0.4s 间隔），但**没有跨任务全局限流**。如果同时跑两个大任务，可能触发 Notion 429。
  - 计划中的「全局速率限制器」未实现（`ratelimit.py` 不存在），见 `GOTCHAS.md`。
