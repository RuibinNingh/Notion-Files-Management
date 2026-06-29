# CLAUDE.md — AI 协作规范(Notion Files Management)

> 给 Claude Code / Claude Agent 的项目级指令。每次新会话开始,**Claude 必须先读 `AI/` 再开工**;任何代码改动后,**Claude 必须同步更新 `AI/`**。

---

## 0. 阅读顺序(每次会话开始时按此顺序)

1. `AI/README.md` — 文档索引、当前服务状态
2. `AI/OVERVIEW.md` — 项目是啥、技术栈、目录
3. `AI/ARCHITECTURE.md` — 数据流、关键设计决策
4. `AI/GOTCHAS.md` — **必读**,16 条坑、临时方案
5. 按需展开 `AI/COMMANDS.md` / `AI/CHANGELOG.md`

**禁止**跳过 AI/ 直接读代码就动刀。

---

## 1. AI/ 文件夹:必读 + 必更(硬性)

`AI/` 是项目自带的交接文档体系,**不是装饰**。Claude 在本项目中的所有工作必须满足:

### 1.1 任何代码改动 → 同步更新 AI/

| 改动类型 | 必须更新 |
|---------|---------|
| 新增/删除/重命名文件 | `AI/OVERVIEW.md` 的目录结构 + `AI/ARCHITECTURE.md` 对应章节 |
| 加新工具、新路由、新 API | `AI/ARCHITECTURE.md` 加流程说明 + `AI/OVERVIEW.md` 路由速览 |
| 改启动/构建/打包命令 | `AI/COMMANDS.md` |
| 踩新坑、临时方案、workaround | `AI/GOTCHAS.md`(格式:现象→原因→解决) |
| 任何对外可见的行为变化 | `AI/CHANGELOG.md`(新条目加最上面,带日期) |
| 架构决策变更 | `AI/ARCHITECTURE.md`「关键设计决策」段落 |

**判断标准**:如果一个新人读 AI/ 仍然能跟上当前代码,说明更新到位了。

### 1.2 新会话开始 → 先读 AI/

Claude 接到任务后,先 `Read AI/README.md` + `AI/OVERVIEW.md` + `AI/GOTCHAS.md`,再开始探索代码。**不要**只看任务描述就上手。

### 1.3 AI/ 格式约束

- 中文为主,代码/命令/路径用英文
- CHANGELOG 新条目**加在最上面**,带日期(格式 `## vX.Y.Z-xxx(YYYY-MM-DD)`)
- GOTCHAS 每条用「**现象 → 原因 → 解决**」三段
- ARCHITECTURE 用 ASCII 数据流图 + 真实代码片段(file_path:line_number)

---

## 2. 工程规范(后端)

### 2.1 每任务一个实例 — 绝对禁止共享

```python
# ✅ 对
def start_download(items, save_dir):
    dl = Download(max_workers=...)   # 新实例
    registry.create("download", poll_fn=lambda: dl.get_status(...), ...)

# ❌ 错(会导致多用户/多任务状态污染)
class NotionFacade:
    self._download = Download(...)    # 全局单例
```

**`Download`、`Upload`、`ScanSession` 实例都按 task_id 一一对应**。`status_map` 不是线程安全的。详见 `AI/ARCHITECTURE.md` 「为什么每任务一个 Download 实例」+ `AI/GOTCHAS.md` 第 6 条。

### 2.2 SSE 终态事件统一用 `done`

```python
# ✅ 对
yield {"event": "done", "data": json.dumps({"status": h.status, "error": h.error})}

# ❌ 错(和 EventSource 原生 error 事件冲突)
yield {"event": "error", "data": ...}
```

`useTask.ts` 只监听 `done` 事件,用 `data.status` 区分 `done/error/cancelled`。改 event 名 = 前端 SSE 监听全废。详见 `AI/GOTCHAS.md` 第 5 条。

### 2.3 facade 的 `start_*` 方法保持同步

```python
@router.post("/api/download/start")
async def start(body: StartIn):                 # async 路由
    h = facade.start_download(items, save_dir)  # 同步调用,内部只入队不阻塞
    return {"task_id": h.task_id}
```

`start_*` 只做 `new Xxx()` + `executor.submit / queue.put`,**不阻塞**。需要阻塞才用 `anyio.to_thread.run_sync`。详见 `AI/ARCHITECTURE.md` 「为什么 facade 同步」。

### 2.4 `backend/scripts/` 用绝对导入

```python
# scripts/upload.py
from logger import PythonLogger       # ✅ 绝对导入
# from .logger import PythonLogger    # ❌ 相对导入会破坏平移
```

`main.py` 第一行把 `backend/scripts/` 加进 `sys.path`,所以原 Scripts/*.py 几乎没改就平移过来了。**不要**改成相对导入。

### 2.5 Notion API 版本

统一 `Notion-Version: 2025-09-03`(含 Data Sources API)。改版本前先验证所有现有路由。

### 2.6 渠道机制(`Status` / `Beta`)

- 默认 `Status`(正式版),环境变量 `NFM_CHANNEL=Beta` 切到预发布
- 不同渠道的 `version.json` / 公告 endpoint 走不同子域(`nfm.ruibin-ningh.top` vs `beta.nfm.ruibin-ningh.top`)
- Settings 页**不暴露** channel 字段(只能 env 改)
- Web 修改不会污染渠道配置

### 2.7 后端依赖管理

- 项目根 `.venv/`(已 gitignore)。**不要**在 `backend/` 下建 `cd backend && python -m venv .venv`(`AI/GOTCHAS.md` 第 13 条)
- 新增 Python 依赖:编辑 `backend/requirements.txt` → `.venv/bin/pip install -r backend/requirements.txt`

### 2.8 第三方开放 API / API Key 鉴权

双通道:`session cookie`(浏览器管理员,全权限)+ `Authorization: Bearer nfm_...`(第三方,受 scope 约束)。`deps.resolve_auth` **先判 session**,session 命中即管理员,不再走 key 校验。

- **API Key 只存 hash**:`config.json` 的 `api_keys[]` 只存 `sha256(明文)`,**永不**存明文。明文只在 `POST /api/apikeys` 创建时返回一次。`public_dict` 已剔除 `api_keys`,**不要**让 hash 经 `/api/settings` 泄露。
- **scope 声明**:路由用 `Depends(require_scope("scan"))` 而非 `require_auth`。业务 scope:`scan/download/upload/tools/tasks`;高危 scope:`settings/system/logs/cache/apikeys`(需显式授权,新建默认不勾)。`system` 路由按端点拆 `logs/cache/system`。
- **错误码**:未认证 401、缺 scope 403、限流超限 429、禁用/过期/伪造 key 一律 401。SSE 终态事件仍统一 `done`(见 2.2)。
- **长期 Key 只走 Bearer**:**任何接口都不接受 `?api_key=`**(避免明文进日志/Referer)。`deps` 不从 query 读 token。第三方 SSE 用短期 `nfmsse_` token:先 `POST /api/tasks/{tid}/events-token`(需 session 或 `tasks` scope)换 10 分钟 token,再 `?events_token=` 订阅。`GET /{tid}/events` 走 `require_events_access`(session/Bearer+tasks/events_token 三选一),**不**挂路由级 `require_scope`。
- **hash 比较**:`verify_key` 用 `secrets.compare_digest`,**不要**改回 `==`。
- **严格 scope**:未知 scope 创建/更新直接 400(`_normalize_scopes` 抛 ValueError),**不**静默过滤。
- **清空过期时间**:`PATCH` 用 `body.model_fields_set` + `update_key` 的 `_UNSET` 哨兵,`{"expires_at": null}` 清空。**不要**改回 `model_dump(exclude_none=True)`(会吞掉 null)。过期时间统一存 UTC ISO。
- **弱 bootstrap 拒绝**:`NFM_BOOTSTRAP_API_KEY` 必须 `nfm_` 前缀 + 负载 ≥ 32 字符,弱值忽略并 warning,**不**自动补前缀。
- **CORS 动态白名单**:`app/cors.py` `DynamicCORSMiddleware` 常驻,每请求读 `config["api_cors_allowed_origins"]`,改设置无需重启。`is_valid_origin` 仅放行 `http(s)` origin,拒 `*`/`null`/带 path;始终 `allow_credentials=true` 故 `*` 永不放行。`SettingsIn` 有 `api_cors_allowed_origins` 字段。**不要**用 starlette 的静态 `CORSMiddleware`(改设置要重启)。
- **预置 key**:env `NFM_BOOTSTRAP_API_KEY` 以 hash 落盘全权限 key,重复启动不重建。

详见 `AI/ARCHITECTURE.md`「鉴权流(双通道)」+ `AI/GOTCHAS.md` 第 22-27 条 + `AI/SECURITY_AUDIT.md`「API Key 开放能力加固」。

---

## 3. 工程规范(前端)

### 3.1 `useTask` 必须返回 `reactive state`

```ts
// ✅ 对(模板里 state.progress.x 自动响应)
export function useTask() {
  const state = reactive({ progress: {}, status: 'idle', error: null, done: false })
  // ...
  return { state, start, stop, cancel }
}

// ❌ 错(模板里 task.progress.x 报 ref 不解包)
export function useTask() {
  return { progress: ref({}), status: ref('idle'), ... }
}
```

详见 `AI/GOTCHAS.md` 第 4 条。

### 3.2 全局样式走 `frontend/src/assets/main.css`(非 scoped)

所有页面级面板样式都在全局 CSS 里:`.panel` / `.panel-head` / `.panel-title` / `.panel-subtitle` / `.status-chip`(+`.ok`/`.warn`/`.err`/`.info`)/ `.muted` / `.action-row` / `.task-list` / `.task-row` / `.task-head` / `.t-name` / `.t-status`(+`.ok`/`.err`/`.wait`)。

**不要**在每个页面重复定义。新页面直接复用这些类。CSS 变量: `--app-primary` / `--app-success` / `--app-warning` / `--app-danger` / `--app-muted` / `--space-2/3/4` / `--radius-md`。

Element Plus 主题对齐:`main.css` 只映射了 `--el-color-primary`,**没映射** `--el-color-success` / `--el-color-error`。如果页面用 `el-step` 等组件的成功/错误态,要在该组件 scoped CSS 里覆盖:
```css
.upload-progress {
  --el-color-success: var(--app-success);
  --el-color-error: var(--app-danger);
}
```

### 3.3 API 客户端:不要重导出 axios

`frontend/src/api/client.ts` 只导出 `api`(axios 实例)和 `errMsg(e)`。要用 `axios.isCancel` / `CanceledError` 等,**直接 `import axios from 'axios'`**。

### 3.4 工具函数入参单位

`utils/format.ts`:
- `fmtSize(mb)` — **入参是兆字节**,字节须先 `/ 1048576`
- `fmtEta(s)` — 入参是秒

不要传错单位。

### 3.5 SSE 终态处理:看 `data.status`

```ts
es.addEventListener('done', (e) => {
  const d = JSON.parse(e.data)
  state.status = d.status   // 'done' | 'error' | 'cancelled'
  state.error = d.error
  state.done = true
})
```

不要监听 `error` 事件名 — 那是 EventSource 的连接断开事件。

---

## 4. 端口与运行环境

| 服务 | 默认端口 | 当前 | 说明 |
|------|---------|------|------|
| 前端 Vite dev | 5173 | 5173 | `frontend/vite.config.ts` proxy 目标 |
| 后端 Uvicorn | 18765 | **18765** | Docker / systemd / Windows exe / 本地开发统一使用 |
| VitePress docs | 5174 | 按 VitePress 自动选择 | 根目录 `npm run docs:dev` |

`frontend/vite.config.ts` 当前 proxy target = `http://127.0.0.1:18765`。后端端口变更时 Docker / systemd / Windows entry / Vite proxy 必须同步。详见 `AI/GOTCHAS.md` 第 2、14 条。

### 登录凭据(开发)
- 密码默认 `admin123`(`AI/README.md` 有写)
- 首次启动时若没设 `NFM_PASSWORD`,会随机生成并打印

---

## 5. 验证清单(改动后必跑)

按改动范围选:

| 改动范围 | 必跑 |
|---------|------|
| 纯前端 | `cd frontend && npm run build`(`vue-tsc -b && vite build`)|
| 纯后端 | `.venv/bin/pytest backend/tests -q` + `py_compile $(find backend/app backend/scripts -name '*.py')` |
| 跨端 | 上面两条 + 手动起服务走查 `AI/COMMANDS.md` 第 5 节 |
| 改架构/路由 | 加 `backend/tests/` 用例 + 更新 `AI/ARCHITECTURE.md` |

**不要**改完不验证就交付。

### 常见构建坑
- `frontend/dist/` 偶尔被 root 占(以前 sudo 跑过),报 `EACCES unlink`。解决:`sudo chown -R $(id -u):$(id -g) frontend/dist` 或用 `npx vite build --outDir dist.verify --emptyOutDir` 验完再删

---

## 6. 禁止项(违反会被架构决策覆盖)

1. ❌ 把 `Download` / `Upload` / `ScanSession` 改成单例或对象池共享
2. ❌ SSE 终态发 `event: "error"`(和 EventSource 原生事件冲突)
3. ❌ 在 `backend/scripts/*.py` 用相对导入
4. ❌ 在 `backend/` 下建 `.venv/`(要在项目根)
5. ❌ 把 `frontend/src/api/client.ts` 的 axios 重导出加回(用 `import axios from 'axios'`)
6. ❌ 把 `composable` 返回的 ref 嵌套在普通对象里(模板会不解包)
7. ❌ 在 Settings 页加 channel 字段(只能 env 改)
8. ❌ 在 router 里直接用 `real_name` 拼路径(走 `save_name`,`AI/GOTCHAS.md` 第 8 条)
9. ❌ 跳过 AI/ 直接读代码动刀
10. ❌ 改完不更新 AI/
11. ❌ 把 API Key 明文落盘(`api_keys[]` 只存 sha256 hash,明文只创建时返回一次)
12. ❌ 让 `api_keys` hash 经 `/api/settings` 的 `public_dict` 泄露(已剔除,别加回去)
13. ❌ 给任何接口加回 `?api_key=` query 支持(长期 Key 只走 Bearer;SSE 用短期 `?events_token=`)
14. ❌ 用已登录的同一个 client 测 Bearer 鉴权(session 优先会绕过 scope,见 `GOTCHAS.md` 第 22 条)
15. ❌ CORS 用 `"*"` 搭配 `allow_credentials=True`(必须显式白名单 origin;动态中间件已禁 `*`)
16. ❌ 把业务路由的 `require_scope(...)` 改回 `require_auth`(会失去 scope 隔离)
17. ❌ 把 `GET /{tid}/events` 挂回路由级 `require_scope`(会让 `?events_token=` 被 401 拦掉,见 `GOTCHAS.md` 第 24 条)
18. ❌ 用 `==` 比较 key hash(用 `secrets.compare_digest`);用 `model_dump(exclude_none=True)` 处理 PATCH(用 `model_fields_set` + `_UNSET`)

---

## 7. 角色 / 范围提示

- **架构意图**:Web 单租户替代原 WPF C# 桌面版;Vue 3 + Element Plus + FastAPI 是当前栈。**不要**引入 React / 其它框架
- **持久化**:配置 + 暂存 + 日志都走 `${NFM_DATA_DIR}`,不引入数据库
- **多租户**:**不在范围内**(`AI/OVERVIEW.md` 「不在范围内」)
- **断点续传**:未实现,优先级低(`AI/GOTCHAS.md` 第 12 条)

---

## 8. Plan / 实施习惯

- 复杂改动先 `EnterPlanMode`,plan 文件写到 `~/.claude/plans/*.md`
- plan 写完用 `ExitPlanMode` 让用户审
- 用户审批前 **不** 改任何文件
- 实施期间用 `TaskCreate` / `TaskUpdate` 跟踪进度
- 用 `file_path:line_number` 引用代码 — 是 clickable 的
